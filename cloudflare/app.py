"""Cloudflare Worker API for the APCLRWA community portal.

The local FastAPI application remains the development implementation. This
module keeps the public API paths and response shapes while replacing local
SQLite/filesystem persistence with D1. Tally snapshots are accepted as bounded
JSON uploads; legacy browser migration remains a separate local-only flow.
"""

from __future__ import annotations

import copy
import hashlib
import json
import secrets
from datetime import date, timedelta
from typing import Any, NoReturn, TypeVar, cast

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from pydantic import ValidationError

try:
    from .portal_models import (
        COLLECTION_NAMES,
        MAX_PAYLOAD_BYTES,
        CollectionWrite,
        PaymentRecord,
        PaymentReview,
        PortalModel,
        ResidentPayment,
        RevisionRequest,
        TallyImport,
        TallyImportApply,
        TallyReconciliation,
        AccountCreate,
        AccountingPeriodCreate,
        JournalCorrectionRequest,
        JournalEntryCreate,
        JournalPostRequest,
        JournalReversalRequest,
        PeriodActionRequest,
    )
except ImportError:
    from portal_models import (
    COLLECTION_NAMES,
    MAX_PAYLOAD_BYTES,
        CollectionWrite,
        PaymentRecord,
    PaymentReview,
    PortalModel,
    ResidentPayment,
    RevisionRequest,
    TallyImport,
    TallyImportApply,
    TallyReconciliation,
    AccountCreate,
    AccountingPeriodCreate,
    JournalCorrectionRequest,
    JournalEntryCreate,
    JournalPostRequest,
    JournalReversalRequest,
    PeriodActionRequest,
    )

try:
    from . import domain
    from .auth import (
        LoginRequest,
        PasswordChangeRequest,
        authenticated_user,
        boolean_setting,
        clear_session_cookie,
        hash_password,
        hash_session_token,
        mark_failed,
        password_matches,
        public_user,
        require_committee,
        reserve_password_attempt,
        session_cookie,
        setting,
        unchanged_password,
        utc_now,
    )
    from .d1 import D1Conflict, D1Error, D1Store
    from . import accounting
except ImportError:
    import domain
    from auth import (
    LoginRequest,
    PasswordChangeRequest,
    authenticated_user,
    boolean_setting,
    clear_session_cookie,
    hash_password,
    hash_session_token,
    mark_failed,
    password_matches,
    public_user,
    require_committee,
    reserve_password_attempt,
    session_cookie,
    setting,
    unchanged_password,
    utc_now,
    )
    from d1 import D1Conflict, D1Error, D1Store
    import accounting


app = FastAPI(title="APCLRWA Portal API", version="0.1.0-cloudflare")
ModelT = TypeVar("ModelT", bound=PortalModel)


def env_for(request: Request) -> Any:
    env = request.scope.get("env")
    if env is None:
        raise HTTPException(status_code=503, detail="The Worker environment is unavailable.")
    return env


def binding(env: Any, name: str) -> Any:
    if isinstance(env, dict):
        return env.get(name)
    return getattr(env, name, None)


def store_for(request: Request) -> D1Store:
    database = binding(env_for(request), "DB")
    if database is None:
        raise HTTPException(status_code=503, detail="The D1 database binding is not configured.")
    return D1Store(database)


def _edge_is_https(request: Request) -> bool:
    visitor = request.headers.get("cf-visitor", "")
    return '"scheme":"https"' in visitor or '"scheme": "https"' in visitor


def _public_scheme(request: Request) -> str:
    return "https" if request.url.scheme == "https" or _edge_is_https(request) else request.url.scheme


def _allowed_origins(request: Request) -> set[str]:
    env = env_for(request)
    configured = setting(env, "APCLRWA_CORS_ORIGINS", "")
    origins = {item.strip().rstrip("/") for item in configured.split(",") if item.strip()}
    origin = f"{_public_scheme(request)}://{request.url.netloc}".rstrip("/")
    # Same-origin requests need no configured CORS entry. Explicit origins are
    # still required for a separately hosted development or custom frontend.
    origins.add(origin)
    return origins


def _cors_headers(request: Request, response: Response) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") in _allowed_origins(request):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Expose-Headers"] = "Retry-After"
        response.headers["Vary"] = "Origin"


@app.middleware("http")
async def security_and_cors(request: Request, call_next: Any) -> Response:
    env = request.scope.get("env")
    production = setting(env, "APCLRWA_ENV", "production").strip().lower() == "production" if env is not None else True
    origin = request.headers.get("origin")
    allowed = False
    if origin:
        try:
            allowed = origin.rstrip("/") in _allowed_origins(request)
        except HTTPException:
            allowed = False
    # The Cloudflare ASGI adapter may expose the edge request as HTTP even
    # though the public Worker URL is HTTPS. Cloudflare has already terminated
    # TLS before invoking the Worker, so the edge URL is the authoritative
    # transport signal for this check.
    edge_is_https = _edge_is_https(request)
    if production and request.url.scheme != "https" and not edge_is_https:
        response = Response(content=json.dumps({"detail": "HTTPS is required."}), status_code=400, media_type="application/json")
    elif origin and not allowed and request.method.upper() not in {"GET", "HEAD"}:
        response = Response(content=json.dumps({"detail": "This request origin is not allowed."}), status_code=403, media_type="application/json")
    elif request.method.upper() == "OPTIONS":
        response = Response(status_code=204)
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Max-Age"] = "600"
    else:
        response = await call_next(request)
    _cors_headers(request, response)
    if request.url.path.startswith("/api/") or getattr(request.state, "authenticated", False):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    if production and _public_scheme(request) == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


def _raise_storage(error: D1Error) -> NoReturn:
    raise HTTPException(status_code=503, detail="The portal storage is temporarily unavailable.") from error


def _invalid(label: str) -> HTTPException:
    return HTTPException(status_code=422, detail=f"Invalid {label} data. Check field names, types, required values, dates and size limits.")


def _model(model_type: type[PortalModel], value: Any, label: str) -> PortalModel:
    try:
        return model_type.model_validate(value)
    except (ValidationError, ValueError, TypeError, OverflowError):
        raise _invalid(label) from None


def _decode_json(raw: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON field.")
            result[key] = value
        return result

    def nonfinite(_: str) -> Any:
        raise ValueError("Nonfinite JSON number.")

    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise HTTPException(400, "The request must contain valid JSON without duplicate fields or nonfinite numbers.") from None


async def _json_body(request: Request, *, limit: int = MAX_PAYLOAD_BYTES) -> Any:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(415, "Send an application/json request body.")
    length = request.headers.get("content-length")
    if length is not None:
        try:
            size = int(length)
        except ValueError:
            raise HTTPException(400, "Invalid content length.") from None
        if size < 0:
            raise HTTPException(400, "Invalid content length.")
        if size > limit:
            raise HTTPException(413, "The request exceeds the payload limit.")
    raw = await request.body()
    if len(raw) > limit:
        raise HTTPException(413, "The request exceeds the payload limit.")
    return _decode_json(raw)


async def _body(request: Request, model_type: type[PortalModel], *, limit: int = MAX_PAYLOAD_BYTES) -> ModelT:
    return cast(ModelT, _model(model_type, await _json_body(request, limit=limit), "request"))


def _tally_apply(value: Any) -> TallyImportApply:
    """Accept the envelope form and the compact direct-snapshot form."""
    if not isinstance(value, dict):
        raise _invalid("Tally import request")
    if "snapshot" in value:
        return cast(TallyImportApply, _model(TallyImportApply, value, "Tally import request"))
    if "revision" not in value:
        raise _invalid("Tally import request")
    snapshot_value = dict(value)
    revision = snapshot_value.pop("revision")
    revision_value = cast(RevisionRequest, _model(RevisionRequest, {"revision": revision}, "request"))
    snapshot = _model(TallyImport, snapshot_value, "Tally import")
    return TallyImportApply(revision=revision_value.revision, snapshot=cast(TallyImport, snapshot))


async def _tally_body(request: Request) -> TallyImportApply:
    value = await _json_body(request)
    if isinstance(value, dict) and "snapshot" not in value and set(value) == {"revision"}:
        raise HTTPException(
            501,
            "The Cloudflare Worker requires the Tally JSON snapshot upload. Choose the snapshot file instead of using the local-file import action.",
        )
    return _tally_apply(value)


async def _load(store: D1Store) -> tuple[int, dict[str, Any]]:
    return await store.load_portal(domain.defaults(), utc_now().isoformat())


async def _load_with_transfers(store: D1Store) -> tuple[int, dict[str, Any]]:
    revision, collections = await _load(store)
    before = copy.deepcopy(collections)
    try:
        domain.ensure_transfers(collections, utc_now().astimezone(domain.KOLKATA).date())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    if collections != before:
        try:
            revision = await store.save_portal(before, collections, revision, utc_now().isoformat())
        except D1Conflict:
            raise HTTPException(409, "Portal data changed. Refresh the portal and retry your change.") from None
    return revision, collections


async def _actor(store: D1Store, user: dict[str, Any], *, committee: bool = False) -> dict[str, Any]:
    row = await store.first("SELECT * FROM users WHERE id = ? AND active = 1", user["id"])
    if row is None:
        raise HTTPException(401, "Your account is inactive. Sign in again.")
    if committee and row["role"] != "committee":
        raise HTTPException(403, "Committee access is required.")
    return row


async def _resident_for_user(store: D1Store, collections: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    account = await _actor(store, user)
    if account["role"] != "resident":
        raise HTTPException(403, "Resident access is required.")
    if account.get("must_change_password"):
        raise HTTPException(403, "Change your temporary password before entering the resident portal.")
    resident_id = account.get("resident_id")
    resident = next((row for row in collections["residents"] if row["id"] == resident_id), None)
    if not resident or not resident["active"]:
        raise HTTPException(403, "This account is not linked to an active backend resident record.")
    return resident


def _public_resident(
    resident: dict[str, Any],
    account: dict[str, Any] | None,
    *,
    include_private: bool = False,
) -> dict[str, Any]:
    sanitized = domain.public_resident(resident, account)
    if not include_private:
        # A resident snapshot may include the opted-in profession because it
        # is suitable for a public directory. The tenant/property-owner name
        # and an unconsented profession remain committee-only fields. The
        # consent bit itself is also committee-only metadata.
        if not sanitized.get("publicProfessionalListing"):
            sanitized.pop("profession", None)
        sanitized.pop("tenantOwnerName", None)
        sanitized.pop("publicProfessionalListing", None)
    return sanitized


async def _snapshot(store: D1Store, revision: int, collections: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    account = await _actor(store, user)
    account_rows = await store.all("SELECT id, resident_id, must_change_password FROM users WHERE role = 'resident' AND resident_id IS NOT NULL")
    accounts = {row["resident_id"]: row for row in account_rows}
    if account["role"] == "committee":
        visible = copy.deepcopy(collections)
        visible["residents"] = [
            _public_resident(row, accounts.get(row["id"]), include_private=True)
            for row in collections["residents"]
        ]
        current = None
    else:
        resident = await _resident_for_user(store, collections, user)
        resident_id = resident["id"]
        current = _public_resident(resident, accounts.get(resident_id), include_private=False)
        visible = {
            "residents": [current],
            "ledger": [row for row in collections["ledger"] if row.get("residentId") == resident_id and row["status"] == "Posted" and row["kind"] in domain.RECEIPT_KINDS],
            "payments": [row for row in collections["payments"] if row.get("residentId") == resident_id],
            "amcRates": collections["amcRates"],
            "events": collections["events"],
            "officeBearers": collections["officeBearers"],
            "openingBalances": None,
            "expenseTypes": [],
            "fixedDeposits": [],
            "tallyReconciliation": None,
        }
    return {"revision": revision, "collections": visible, "currentResident": current}


async def _validate_accounts(store: D1Store, residents: list[dict[str, Any]]) -> None:
    try:
        domain.validate_resident_uniqueness(residents)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    users = await store.all("SELECT id, username, role, resident_id FROM users")
    seen_resident_ids: set[str] = set()
    usernames: dict[str, list[dict[str, Any]]] = {}
    for user in users:
        if user.get("resident_id") is not None:
            if user["role"] != "resident" or user["resident_id"] in seen_resident_ids:
                raise HTTPException(409, "Resident account links are ambiguous. Repair the account links before saving.")
            seen_resident_ids.add(user["resident_id"])
        existing = str(user["username"]).strip().casefold()
        try:
            phone = domain.normalize_mobile(existing)
        except ValueError:
            phone = existing
        for key in {existing, phone}:
            usernames.setdefault(key, []).append(user)
    for resident in residents:
        username = resident["mobile"].strip().casefold()
        for user in usernames.get(username, []):
            if not (user["role"] == "resident" and user.get("resident_id") == resident["id"]):
                raise HTTPException(409, "A resident phone number conflicts with another authentication account.")


async def _sync_accounts(
    store: D1Store,
    residents: list[dict[str, Any]],
    passwords: dict[str, str],
    previous: list[dict[str, Any]],
    now: str,
) -> tuple[list[tuple[str, tuple[Any, ...]]], bool]:
    accounts = await store.all("SELECT * FROM users WHERE role = 'resident'")
    by_id = {row["id"]: row for row in residents}
    previous_by_id = {row["id"]: row for row in previous}
    linked = {row["resident_id"]: row for row in accounts if row.get("resident_id") is not None}
    statements: list[tuple[str, tuple[Any, ...]]] = []
    changed = False
    for account in accounts:
        resident = by_id.get(account.get("resident_id"))
        if resident is None:
            if account.get("resident_id") not in previous_by_id:
                continue
            if account.get("active"):
                statements.append(("UPDATE users SET active = 0 WHERE id = ?", (account["id"],)))
                changed = True
            statements.append(("DELETE FROM sessions WHERE user_id = ?", (account["id"],)))
            continue
        username = resident["mobile"].strip().casefold()
        password = passwords.get(resident["id"])
        previous_resident = previous_by_id.get(resident["id"])
        active = int(account["active"]) if resident["active"] else 0
        if resident["active"] and (password or (previous_resident and not previous_resident["active"])):
            active = 1
        if password or not active or account["username"] != username:
            statements.append(("DELETE FROM sessions WHERE user_id = ?", (account["id"],)))
        if (account["username"], account["display_name"], int(account["active"])) != (username, resident["name"], active):
            statements.append(("UPDATE users SET username = ?, display_name = ?, active = ? WHERE id = ?", (username, resident["name"], active, account["id"])))
            changed = True
        if password:
            salt = secrets.token_bytes(16)
            statements.append((
                "UPDATE users SET password_scheme = ?, password_salt = ?, password_hash = ?, must_change_password = 1 WHERE id = ?",
                ("pbkdf2-sha256", salt.hex(), (await hash_password(password, salt)).hex(), account["id"]),
            ))
            changed = True
    for resident in residents:
        password = passwords.get(resident["id"])
        if resident["id"] in linked or not password:
            continue
        salt = secrets.token_bytes(16)
        statements.append((
            """INSERT INTO users(id, username, display_name, role, password_salt, password_hash,
                                  active, created_at, resident_id, must_change_password, password_scheme)
               VALUES (?, ?, ?, 'resident', ?, ?, ?, ?, ?, 1, ?)""",
            (
                "USR-" + secrets.token_hex(16), resident["mobile"].strip().casefold(), resident["name"],
                salt.hex(), (await hash_password(password, salt)).hex(), int(resident["active"]), now, resident["id"], "pbkdf2-sha256",
            ),
        ))
        changed = True
    return statements, changed


def _check_revision(actual: int, expected: int) -> None:
    if actual != expected:
        raise HTTPException(409, "Portal data changed. Refresh the portal and retry your change.")


def _tally_domain_error(error: ValueError) -> HTTPException:
    message = str(error).casefold()
    if "conflict" in message:
        return HTTPException(409, "The imported Tally data conflicts with existing portal data.")
    if "exceeds" in message or "record limit" in message:
        return HTTPException(413, "The imported Tally data exceeds the portal storage limit.")
    return HTTPException(422, "The imported Tally data could not be applied.")


def _without_imported_at(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    result = copy.deepcopy(value)
    result.pop("importedAt", None)
    return result


def _same_imported_ledger(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> bool:
    indexed = {row["id"]: row for row in existing}
    return all(indexed.get(row["id"]) == row for row in incoming)


def _tally_metadata(snapshot: TallyImport, ledger: list[dict[str, Any]]) -> dict[str, Any]:
    metadata = domain.json_record(snapshot.reconciliation)
    metadata.update(
        importId=snapshot.importId,
        sourceFiles=list(snapshot.sourceFiles),
        transactionCount=len(ledger),
    )
    return metadata


def _prepare_tally_ledger(
    snapshot: TallyImport,
    existing: list[dict[str, Any]],
    residents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    try:
        ledger, _ = domain.collection(
            "ledger",
            [domain.json_record(row) for row in snapshot.transactions],
            deduplicate=True,
        )
    except ValueError:
        raise _invalid("Tally ledger") from None
    if any(row["status"] != "Posted" or row.get("paymentId") for row in ledger):
        raise HTTPException(
            422,
            "The Tally snapshot must contain posted book entries, not payment claims or server-managed payment receipts.",
        )
    try:
        return domain.bind_records("ledger", ledger, residents, existing)
    except ValueError:
        raise _invalid("Tally ledger") from None


async def _apply_tally(store: D1Store, payload: TallyImportApply, user: dict[str, Any]) -> dict[str, Any]:
    """Apply one validated Tally snapshot without requiring R2 or local files."""
    await _actor(store, user, committee=True)
    revision, existing = await _load(store)
    snapshot = payload.snapshot
    incoming_ledger = _prepare_tally_ledger(snapshot, existing["ledger"], existing["residents"])
    metadata = _tally_metadata(snapshot, incoming_ledger)
    incoming_opening = domain.json_record(snapshot.openingBalances) if snapshot.openingBalances is not None else None
    existing_opening = existing["openingBalances"]
    prior_reconciliation = existing["tallyReconciliation"]
    same_import_id = isinstance(prior_reconciliation, dict) and prior_reconciliation.get("importId") == snapshot.importId

    if existing_opening is not None and incoming_opening is not None and existing_opening != incoming_opening:
        raise HTTPException(409, "The imported opening balances conflict with existing portal data.")
    if same_import_id and existing_opening is None and incoming_opening is not None:
        raise HTTPException(409, "The imported Tally snapshot conflicts with existing portal data.")

    if same_import_id:
        if (
            _without_imported_at(prior_reconciliation) != _without_imported_at(metadata)
            or not _same_imported_ledger(existing["ledger"], incoming_ledger)
        ):
            raise HTTPException(409, "The imported Tally snapshot conflicts with the existing import.")
        new = copy.deepcopy(existing)
        try:
            domain.ensure_transfers(new, utc_now().astimezone(domain.KOLKATA).date())
            domain.validate_storage_limits(new)
        except ValueError as exc:
            raise _tally_domain_error(exc) from None
        if new == existing:
            return await _snapshot(store, revision, existing, user)
        now = utc_now().isoformat()
        try:
            next_revision = await store.save_portal(existing, new, revision, now)
        except D1Conflict:
            raise HTTPException(409, "Portal data changed. Refresh the portal and retry your change.") from None
        return await _snapshot(store, next_revision, new, user)

    _check_revision(revision, payload.revision)
    new = copy.deepcopy(existing)
    try:
        new["ledger"] = domain.merge_ledger_append_only(existing["ledger"], incoming_ledger)
    except ValueError as exc:
        raise _tally_domain_error(exc) from None
    if existing_opening is None and incoming_opening is not None:
        new["openingBalances"] = incoming_opening

    if (
        isinstance(prior_reconciliation, dict)
        and _without_imported_at(prior_reconciliation) == _without_imported_at(metadata)
        and prior_reconciliation.get("importedAt")
    ):
        metadata["importedAt"] = prior_reconciliation["importedAt"]
    else:
        metadata["importedAt"] = utc_now().isoformat()
    new["tallyReconciliation"] = domain.json_record(
        cast(TallyReconciliation, _model(TallyReconciliation, metadata, "Tally reconciliation"))
    )
    try:
        domain.ensure_transfers(new, utc_now().astimezone(domain.KOLKATA).date())
        domain.validate_storage_limits(new)
    except ValueError as exc:
        raise _tally_domain_error(exc) from None
    now = utc_now().isoformat()
    try:
        next_revision = await store.save_portal(existing, new, revision, now)
    except D1Conflict:
        raise HTTPException(409, "Portal data changed. Refresh the portal and retry your change.") from None
    return await _snapshot(store, next_revision, new, user)


async def _write_collection(store: D1Store, name: str, payload: CollectionWrite, user: dict[str, Any], env: Any) -> dict[str, Any]:
    if name not in COLLECTION_NAMES:
        raise HTTPException(404, "Unknown portal collection.")
    try:
        value, passwords = domain.collection(name, payload.value)
    except ValueError as exc:
        raise _invalid(name) from exc
    revision, old = await _load_with_transfers(store)
    _check_revision(revision, payload.revision)
    new = copy.deepcopy(old)
    if name in {"ledger", "payments"}:
        try:
            value = domain.bind_records(name, value, old["residents"], old[name])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    if name == "ledger":
        try:
            domain.guard_ledger_update(old[name], value)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    if name == "payments":
        try:
            value = domain.guard_payment_update(old[name], value)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    new[name] = value
    if name == "residents":
        await _validate_accounts(store, value)
    try:
        domain.ensure_transfers(new, utc_now().astimezone(domain.KOLKATA).date())
        domain.validate_storage_limits(new)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    now = utc_now().isoformat()
    account_statements: list[tuple[str, tuple[Any, ...]]] = []
    account_changes = False
    if name == "residents":
        account_statements, account_changes = await _sync_accounts(store, value, passwords, old["residents"], now)
    try:
        next_revision = await store.save_portal(old, new, revision, now, force=account_changes, extra_statements=account_statements)
    except D1Conflict:
        raise HTTPException(409, "Portal data changed. Refresh the portal and retry your change.") from None
    except D1Error as exc:
        _raise_storage(exc)
    return await _snapshot(store, next_revision, new, user)


async def _resident_payment(store: D1Store, payload: ResidentPayment, user: dict[str, Any], env: Any) -> dict[str, Any]:
    revision, old = await _load_with_transfers(store)
    resident = await _resident_for_user(store, old, user)
    fingerprint = hashlib.sha256(domain.json_text(payload.model_dump(exclude={"idempotencyKey"})).encode("utf-8")).hexdigest()
    prior = await store.first(
        "SELECT request_hash, payment_id FROM portal_payment_keys WHERE resident_id = ? AND idempotency_key = ?",
        resident["id"],
        payload.idempotencyKey,
    )
    if prior:
        if prior["request_hash"] != fingerprint:
            raise HTTPException(409, "This idempotency key was already used for a different payment.")
        return await _snapshot(store, revision, old, user)
    now_dt = utc_now()
    today = now_dt.astimezone(domain.KOLKATA).date()
    target_fy = domain.amc_financial_year(today)
    if payload.type == "Maintenance":
        if today.month > 3:
            raise HTTPException(422, "Resident AMC payment claims are accepted only from January 1 through March 31.")
        if resident["residentType"] not in {"Owner", "Tenant"}:
            raise HTTPException(422, "The committee must set your owner or tenant status before AMC payment.")
        due = domain.amount_due(old, resident, target_fy)
        if due <= 0 or abs(payload.numericAmount - due) > 0.005:
            raise HTTPException(422, "The AMC claim amount must match this resident's outstanding AMC charge.")
    if payload.type == "Membership" and (resident["initialChargePaid"] or payload.numericAmount != 500):
        raise HTTPException(422, "Membership claims must be for the unpaid one-time charge of 500.")
    if payload.type in {"Maintenance", "Membership"}:
        pending = [row for row in old["payments"] if row.get("residentId") == resident["id"] and row["type"] == payload.type and row["status"] == "Pending verification"]
        if any(payload.type == "Membership" or row.get("amcForFinancialYear", row["financialYear"]) == target_fy for row in pending):
            raise HTTPException(409, "A claim for this charge is already awaiting committee verification.")
    claim: dict[str, Any] = {
        "id": "PAY-" + secrets.token_hex(16),
        "residentId": resident["id"],
        "resident": resident["name"],
        "mobile": resident["mobile"],
        "house": resident["house"],
        "type": payload.type,
        "numericAmount": payload.numericAmount,
        "amount": domain.format_amount(payload.numericAmount),
        "date": domain.display_date(today.isoformat()),
        "transactionDate": today.isoformat(),
        "createdAt": now_dt.isoformat(),
        "financialYear": domain.financial_year(today),
        "status": "Pending verification",
        "mode": payload.mode,
        "details": payload.details,
    }
    if payload.type == "Maintenance":
        claim.update(amcForFinancialYear=target_fy, amcBucket="Advance AMC")
    claim = domain.json_record(_model(PaymentRecord, claim, "payment"))
    new = copy.deepcopy(old)
    new["payments"].append(claim)
    try:
        domain.ensure_transfers(new, today)
        domain.validate_storage_limits(new)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    extra = [(
        "INSERT INTO portal_payment_keys(resident_id, idempotency_key, request_hash, payment_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (resident["id"], payload.idempotencyKey, fingerprint, claim["id"], now_dt.isoformat()),
    )]
    try:
        next_revision = await store.save_portal(old, new, revision, now_dt.isoformat(), extra_statements=extra)
    except D1Conflict as exc:
        if "portal revision conflict" in str(exc).lower():
            raise HTTPException(409, "Portal data changed. Refresh the portal and retry your change.") from None
        repeated = await store.first(
            "SELECT request_hash FROM portal_payment_keys WHERE resident_id = ? AND idempotency_key = ?",
            resident["id"],
            payload.idempotencyKey,
        )
        if repeated and repeated["request_hash"] == fingerprint:
            latest_revision, latest = await _load_with_transfers(store)
            return await _snapshot(store, latest_revision, latest, user)
        raise HTTPException(409, "This idempotency key was already used for a different payment.") from None
    except D1Error as exc:
        _raise_storage(exc)
    return await _snapshot(store, next_revision, new, user)


async def _review_payment(store: D1Store, payment_id: str, payload: PaymentReview, user: dict[str, Any]) -> dict[str, Any]:
    actor = await _actor(store, user, committee=True)
    revision, old = await _load_with_transfers(store)
    _check_revision(revision, payload.revision)
    new = copy.deepcopy(old)
    claim = next((row for row in new["payments"] if row["id"] == payment_id), None)
    if claim is None:
        raise HTTPException(404, "The payment claim was not found.")
    if claim["status"] == payload.status:
        return await _snapshot(store, revision, old, user)
    if claim["status"] != "Pending verification":
        raise HTTPException(409, "This payment has already been reviewed.")
    now = utc_now().isoformat()
    if payload.status == "Approved":
        if claim["type"] == "Membership":
            resident = next((row for row in new["residents"] if row["id"] == claim.get("residentId")), None)
            if not resident or claim["numericAmount"] != 500:
                raise HTTPException(422, "Membership approval requires a valid linked resident and a charge of 500.")
            details = {"date": claim["transactionDate"], "mode": claim["mode"], "details": claim["details"]}
            if resident["initialChargePaid"] and resident.get("membershipPayment") != details:
                raise HTTPException(409, "The one-time membership charge is already recorded as paid with different payment details.")
            resident.update(initialChargePaid=True, membershipPayment=details)
            receipt = domain.posted_receipt(claim, now)
            existing = next((row for row in new["ledger"] if row.get("kind") == "Membership" and row.get("status") == "Posted" and row.get("residentId") == resident["id"] and row.get("amount") == receipt["amount"] and row.get("date") == receipt["date"]), None)
            if existing is None:
                new["ledger"].append(receipt)
                existing = receipt
            claim["ledgerId"] = existing["id"]
        else:
            if claim["type"] == "Maintenance" and not any(row["id"] == claim.get("residentId") for row in new["residents"]):
                raise HTTPException(422, "Maintenance approval requires a valid linked resident.")
            receipt = domain.posted_receipt(claim, now)
            existing = next((row for row in new["ledger"] if row["id"] == receipt["id"]), None)
            if existing:
                comparable = dict(existing)
                comparable.setdefault("paymentId", claim["id"])
                if comparable != receipt:
                    raise HTTPException(409, "This claim's receipt ID conflicts with an existing ledger record.")
                existing["paymentId"] = claim["id"]
            else:
                new["ledger"].append(receipt)
            claim["ledgerId"] = receipt["id"]
    claim.update(status=payload.status, reviewedAt=now, reviewedBy=actor["username"])
    try:
        domain.ensure_transfers(new, utc_now().astimezone(domain.KOLKATA).date())
        domain.validate_storage_limits(new)
        next_revision = await store.save_portal(old, new, revision, now)
    except D1Conflict:
        raise HTTPException(409, "Portal data changed. Refresh the portal and retry your change.") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except D1Error as exc:
        _raise_storage(exc)
    return await _snapshot(store, next_revision, new, user)


async def _login(store: D1Store, payload: LoginRequest, request: Request, response: Response, env: Any) -> dict[str, Any]:
    username = payload.username.strip().casefold()
    attempt_id = await reserve_password_attempt(store, request, env, username)
    row = await store.first("SELECT * FROM users WHERE username = ? AND active = 1", username)
    matches = await password_matches(row, payload.password)
    if not matches or row is None or row["role"] != payload.role:
        await mark_failed(store, attempt_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Username or password is incorrect.")
    current = await store.first("SELECT * FROM users WHERE id = ? AND active = 1", row["id"])
    if current is None or not unchanged_password(row, current) or current["role"] != payload.role:
        await mark_failed(store, attempt_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Username or password is incorrect.")
    token = secrets.token_urlsafe(32)
    now = utc_now()
    expires_at = now + timedelta(hours=int(setting(env, "APCLRWA_SESSION_HOURS", "12")))
    previous_token = request.cookies.get("apclrwa_session")
    statements: list[tuple[str, tuple[Any, ...]]] = [
        ("DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(),)),
    ]
    if previous_token and len(previous_token) <= 256:
        statements.append(("DELETE FROM sessions WHERE token_hash = ?", (hash_session_token(previous_token),)))
    statements.extend([
        ("INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)", (hash_session_token(token), row["id"], expires_at.isoformat(), now.isoformat())),
        ("UPDATE auth_attempts SET outcome = 'succeeded' WHERE id = ?", (attempt_id,)),
        ("UPDATE auth_attempts SET outcome = 'cleared' WHERE account_key = ? AND outcome = 'failed'", (hashlib.sha256(username.encode("utf-8")).hexdigest(),)),
    ])
    try:
        await store.batch(statements)
    except D1Error as exc:
        _raise_storage(exc)
    session_cookie(response, token, env)
    return {"user": public_user(current), "expiresAt": expires_at.isoformat()}


async def _change_password(store: D1Store, payload: PasswordChangeRequest, request: Request, user: dict[str, Any], env: Any) -> dict[str, Any]:
    attempt_id = await reserve_password_attempt(store, request, env, user["username"])
    row = await store.first("SELECT * FROM users WHERE id = ? AND active = 1", user["id"])
    if row is None or not await password_matches(row, payload.current_password):
        await mark_failed(store, attempt_id)
        raise HTTPException(401, "Current password is incorrect.")
    token = request.cookies.get("apclrwa_session")
    if not token or len(token) > 256:
        await mark_failed(store, attempt_id)
        raise HTTPException(401, "Your session has expired. Sign in again.")
    current = await store.first(
        """
        SELECT users.* FROM users JOIN sessions ON users.id = sessions.user_id
        WHERE users.id = ? AND users.active = 1 AND sessions.token_hash = ? AND sessions.expires_at > ?
        """,
        user["id"],
        hash_session_token(token),
        utc_now().isoformat(),
    )
    if current is None or not unchanged_password(row, current):
        await mark_failed(store, attempt_id)
        raise HTTPException(401, "Your credentials changed. Sign in again.")
    salt = secrets.token_bytes(16)
    password_hash = await hash_password(payload.new_password, salt)
    now = utc_now().isoformat()
    account_key = hashlib.sha256(user["username"].strip().casefold().encode("utf-8")).hexdigest()
    statements: list[tuple[str, tuple[Any, ...]]] = [
        ("UPDATE users SET password_scheme = ?, password_salt = ?, password_hash = ?, must_change_password = 0 WHERE id = ?", ("pbkdf2-sha256", salt.hex(), password_hash.hex(), user["id"])),
        ("DELETE FROM sessions WHERE user_id = ? AND token_hash <> ?", (user["id"], hash_session_token(token))),
        ("UPDATE auth_attempts SET outcome = 'succeeded' WHERE id = ?", (attempt_id,)),
        ("UPDATE auth_attempts SET outcome = 'cleared' WHERE account_key = ? AND outcome = 'failed'", (account_key,)),
    ]
    try:
        await store.batch(statements)
    except D1Error as exc:
        _raise_storage(exc)
    updated = await store.first("SELECT * FROM users WHERE id = ?", user["id"])
    if updated is None:
        raise HTTPException(401, "Your credentials changed. Sign in again.")
    return {"user": public_user(updated)}


@app.get("/api/health")
async def health(request: Request) -> dict[str, str]:
    try:
        await store_for(request).ping()
    except HTTPException:
        raise
    except D1Error as exc:
        _raise_storage(exc)
    return {"status": "ok"}


@app.post("/api/auth/login")
async def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    try:
        return await _login(store_for(request), payload, request, response, env_for(request))
    except HTTPException:
        raise
    except D1Error as exc:
        _raise_storage(exc)


@app.get("/api/auth/me")
async def current_session(request: Request) -> dict[str, Any]:
    return {"user": await authenticated_user(store_for(request), request)}


@app.post("/api/auth/password")
async def change_password(payload: PasswordChangeRequest, request: Request) -> dict[str, Any]:
    return await _change_password(store_for(request), payload, request, await authenticated_user(store_for(request), request), env_for(request))


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response) -> dict[str, str]:
    token = request.cookies.get("apclrwa_session")
    if token and len(token) <= 256:
        try:
            await store_for(request).run("DELETE FROM sessions WHERE token_hash = ?", hash_session_token(token))
        except D1Error as exc:
            _raise_storage(exc)
    clear_session_cookie(response, env_for(request))
    return {"status": "signed out"}


@app.get("/api/admin/session")
async def committee_session(request: Request) -> dict[str, Any]:
    return {"user": await require_committee(store_for(request), request), "authorized": True}


@app.get("/api/public/content")
async def public_content(request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    try:
        _, collections = await _load(store)
    except D1Error as exc:
        _raise_storage(exc)
    response.headers["Cache-Control"] = "no-store"
    return {
        "events": [row for row in collections["events"] if not row.get("residentsOnly", False)],
        "officeBearers": collections["officeBearers"],
        "professionals": [
            {
                "name": row["name"],
                "house": row["house"],
                "profession": row["profession"],
                "contact": row["mobile"],
            }
            for row in collections["residents"]
            if row.get("active") and row.get("publicProfessionalListing") and row.get("profession")
        ],
        "contacts": domain.public_contacts(collections["officeBearers"]),
    }


@app.get("/api/portal")
async def portal_snapshot(request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    user = await authenticated_user(store, request)
    try:
        revision, collections = await _load_with_transfers(store)
        result = await _snapshot(store, revision, collections, user)
    except D1Error as exc:
        _raise_storage(exc)
    response.headers["Cache-Control"] = "no-store"
    return result


@app.post("/api/admin/collections/{name}")
async def replace_collection(name: str, request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    user = await require_committee(store, request)
    payload = await _body(request, CollectionWrite)
    result = await _write_collection(store, name, payload, user, env_for(request))
    response.headers["Cache-Control"] = "no-store"
    return result


@app.post("/api/resident/payments")
async def submit_resident_payment(request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    user = await authenticated_user(store, request)
    payload = await _body(request, ResidentPayment, limit=32 * 1024)
    result = await _resident_payment(store, payload, user, env_for(request))
    response.headers["Cache-Control"] = "no-store"
    return result


@app.post("/api/admin/payments/{payment_id}/review")
async def review_payment(payment_id: str, request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    user = await require_committee(store, request)
    payload = await _body(request, PaymentReview, limit=4096)
    result = await _review_payment(store, payment_id, payload, user)
    response.headers["Cache-Control"] = "no-store"
    return result


@app.post("/api/admin/tally-import/apply")
@app.post("/api/admin/tally-import/upload")
async def apply_tally_import(request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    user = await require_committee(store, request)
    payload = await _tally_body(request)
    try:
        result = await _apply_tally(store, payload, user)
    except HTTPException:
        raise
    except D1Error as exc:
        _raise_storage(exc)
    response.headers["Cache-Control"] = "no-store"
    return result


@app.api_route("/api/admin/migration/preview", methods=["POST"])
@app.api_route("/api/admin/migration/import", methods=["POST"])
@app.api_route("/api/admin/tally-import", methods=["GET"])
async def unsupported_local_storage_routes(request: Request) -> Response:
    store = store_for(request)
    await require_committee(store, request)
    return Response(
        content=json.dumps({"detail": "This local-file migration flow is not available in the Cloudflare Worker."}),
        status_code=501,
        media_type="application/json",
    )


@app.get("/api/admin/accounting/accounts")
@app.get("/api/admin/accounting/chart-of-accounts")
async def accounting_accounts(request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    await require_committee(store, request)
    try:
        result = await accounting.list_accounts(store)
    except D1Error as exc:
        _raise_storage(exc)
    response.headers["Cache-Control"] = "no-store"
    return {"accounts": result}


@app.post("/api/admin/accounting/accounts")
@app.post("/api/admin/accounting/chart-of-accounts")
async def accounting_create_account(request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    user = await require_committee(store, request)
    payload = await _body(request, AccountCreate, limit=32 * 1024)
    try:
        result = await accounting.create_account(store, payload, user, utc_now().isoformat())
    except HTTPException:
        raise
    except D1Error as exc:
        _raise_storage(exc)
    response.headers["Cache-Control"] = "no-store"
    return {"account": result}


@app.get("/api/admin/accounting/periods")
async def accounting_periods(request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    await require_committee(store, request)
    try:
        result = await accounting.list_periods(store)
    except D1Error as exc:
        _raise_storage(exc)
    response.headers["Cache-Control"] = "no-store"
    return {"periods": result}


@app.post("/api/admin/accounting/periods")
async def accounting_create_period(request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    user = await require_committee(store, request)
    payload = await _body(request, AccountingPeriodCreate, limit=16 * 1024)
    try:
        result = await accounting.create_period(store, payload, user, utc_now().isoformat())
    except HTTPException:
        raise
    except D1Error as exc:
        _raise_storage(exc)
    response.headers["Cache-Control"] = "no-store"
    return {"period": result}


@app.get("/api/admin/accounting/journal-entries")
@app.get("/api/admin/accounting/entries")
async def accounting_entries(request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    await require_committee(store, request)
    try:
        result = await accounting.list_entries(store)
    except D1Error as exc:
        _raise_storage(exc)
    response.headers["Cache-Control"] = "no-store"
    return {"entries": result}


@app.get("/api/admin/accounting/journal-entries/{entry_id}")
@app.get("/api/admin/accounting/entries/{entry_id}")
async def accounting_entry(entry_id: str, request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    await require_committee(store, request)
    try:
        result = await accounting._entry_record(store, entry_id)
    except HTTPException:
        raise
    except D1Error as exc:
        _raise_storage(exc)
    response.headers["Cache-Control"] = "no-store"
    return {"entry": result}


@app.post("/api/admin/accounting/journal-entries")
@app.post("/api/admin/accounting/entries")
async def accounting_create_entry(request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    user = await require_committee(store, request)
    payload = await _body(request, JournalEntryCreate, limit=256 * 1024)
    try:
        result = await accounting.create_entry(store, payload, user, utc_now().isoformat())
    except HTTPException:
        raise
    except D1Error as exc:
        _raise_storage(exc)
    response.headers["Cache-Control"] = "no-store"
    return {"entry": result}


@app.post("/api/admin/accounting/journal-entries/{entry_id}/post")
@app.post("/api/admin/accounting/entries/{entry_id}/post")
async def accounting_post_entry(entry_id: str, request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    user = await require_committee(store, request)
    payload = await _body(request, JournalPostRequest, limit=16 * 1024)
    try:
        result = await accounting.post_entry(store, entry_id, payload, user, utc_now().isoformat())
    except HTTPException:
        raise
    except D1Error as exc:
        _raise_storage(exc)
    response.headers["Cache-Control"] = "no-store"
    return {"entry": result}


@app.post("/api/admin/accounting/journal-entries/{entry_id}/reverse")
@app.post("/api/admin/accounting/entries/{entry_id}/reverse")
async def accounting_reverse_entry(entry_id: str, request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    user = await require_committee(store, request)
    payload = await _body(request, JournalReversalRequest, limit=32 * 1024)
    try:
        result = await accounting.reverse_entry(store, entry_id, payload, user, utc_now().isoformat())
    except HTTPException:
        raise
    except D1Error as exc:
        _raise_storage(exc)
    response.headers["Cache-Control"] = "no-store"
    return {"entry": result}


@app.post("/api/admin/accounting/journal-entries/{entry_id}/correct")
@app.post("/api/admin/accounting/entries/{entry_id}/correct")
async def accounting_correct_entry(entry_id: str, request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    user = await require_committee(store, request)
    payload = await _body(request, JournalCorrectionRequest, limit=256 * 1024)
    try:
        result = await accounting.correct_entry(store, entry_id, payload, user, utc_now().isoformat())
    except HTTPException:
        raise
    except D1Error as exc:
        _raise_storage(exc)
    response.headers["Cache-Control"] = "no-store"
    return {"entry": result}


@app.post("/api/admin/accounting/periods/{period_id}/close")
async def accounting_close_period(period_id: str, request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    user = await require_committee(store, request)
    payload = await _body(request, PeriodActionRequest, limit=16 * 1024)
    try:
        result = await accounting.close_period(store, period_id, payload, user, utc_now().isoformat())
    except HTTPException:
        raise
    except D1Error as exc:
        _raise_storage(exc)
    response.headers["Cache-Control"] = "no-store"
    return {"period": result}


@app.post("/api/admin/accounting/periods/{period_id}/reopen")
async def accounting_reopen_period(period_id: str, request: Request, response: Response) -> dict[str, Any]:
    store = store_for(request)
    user = await require_committee(store, request)
    payload = await _body(request, PeriodActionRequest, limit=16 * 1024)
    try:
        result = await accounting.reopen_period(store, period_id, payload, user, utc_now().isoformat())
    except HTTPException:
        raise
    except D1Error as exc:
        _raise_storage(exc)
    response.headers["Cache-Control"] = "no-store"
    return {"period": result}


@app.get("/api/admin/accounting/audit-events")
@app.get("/api/admin/accounting/audit")
async def accounting_audit(
    request: Request,
    response: Response,
    periodId: str | None = None,
    entityType: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    store = store_for(request)
    await require_committee(store, request)
    try:
        result = await accounting.list_audit_events(store, period_id=periodId, entity_type=entityType, limit=limit)
    except D1Error as exc:
        _raise_storage(exc)
    response.headers["Cache-Control"] = "no-store"
    return {"events": result}
