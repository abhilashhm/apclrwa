"""SQLite-backed operational portal, with explicit, committee-driven imports.

Import this router after auth's dependency definitions and call
initialize_portal() after initialize_database(). All auth imports are lazy so
the auth application can include this router without a module import cycle.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .portal_models import (
    COLLECTION_NAMES, MAX_COLLECTION_ROWS, MAX_PAYLOAD_BYTES, ROW_MODELS,
    CollectionWrite, LedgerEntry, MigrationImport, MigrationPreview,
    OpeningBalances, PaymentRecord, PaymentReview, PortalModel,
    ResidentPayment, RevisionRequest, TallyImport, TallyReconciliation,
    finite_legacy_amount, iso_date, json_record, normalize_mobile,
)


router = APIRouter()
# Asia/Kolkata has used UTC+05:30 without DST throughout all supported portal
# financial years. A fixed offset also works on Windows without a tzdata wheel.
KOLKATA = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
RECEIPT_KINDS = {"Maintenance", "Advance AMC", "AMC Transfer", "Collections", "Membership"}
DEFAULT_AMC_RATES = [
    {"financialYear": "2026–27", "owner": 1000, "tenant": 500},
    {"financialYear": "2027–28", "owner": 1500, "tenant": 800},
]
DEFAULT_EXPENSE_TYPES = [
    "Waterman Charges", "Printing & Stationery", "Office Rent", "Office Expenses",
    "AGM Expenses", "Ganesha Festival Expenses", "Electricity Charges",
    "Cultural Program Expenses", "Repairs & Maintenance", "Bank Charges", "Audit Fees",
]
DEFAULT_OFFICE_BEARERS = [
    {"name": "Sh. K Bhaskarachar", "display": "Sri. K Bhaskarachar", "role": "President", "phone": ""},
    {"name": "Sh. Mahesh Krishnamurthy", "display": "Sri. Mahesh Krishnamurthy", "role": "General Secretary", "phone": ""},
    {"name": "Sh. Krishna Rao", "display": "Sri. Krishna Rao", "role": "Vice President 1", "phone": ""},
    {"name": "Smt. Roopa Rakesh", "display": "Smt. Roopa Rakesh", "role": "Vice President 2", "phone": ""},
    {"name": "Sh. Elangovan", "display": "Sri. Elangovan", "role": "Joint Secretary 1", "phone": ""},
    {"name": "Sh. Sunil Ghorpade", "display": "Sri. Sunil Ghorpade", "role": "Joint Secretary 2", "phone": ""},
    {"name": "Sh. Manjunath B K", "display": "Sri. Manjunath B K", "role": "Organising Secretary", "phone": ""},
    {"name": "Smt. Sowjanya", "display": "Smt. Sowjanya", "role": "Assistant Secretary", "phone": ""},
    {"name": "Sh. Abhilash", "display": "Sri. Abhilash", "role": "Treasurer", "phone": ""},
    {"name": "Sh. Mahesh More", "display": "Sri. Mahesh More", "role": "Office Secretary", "phone": ""},
    {"name": "Sh. Srihari", "display": "Sri. Srihari", "role": "Executive Committee Member", "phone": ""},
    {"name": "Sh. Nagesh Kumble", "display": "Sri. Nagesh Kumble", "role": "Executive Committee Member", "phone": ""},
    {"name": "Sh. Vasudev", "display": "Sri. Vasudev", "role": "Executive Committee Member", "phone": ""},
    {"name": "Sh. Rakesh Naidu", "display": "Sri. Rakesh Naidu", "role": "Executive Committee Member", "phone": ""},
]
OFFICIAL_PUBLIC_CONTACTS = [
    {
        "id": "emergency-112",
        "label": "Emergency response",
        "number": "112",
        "kind": "emergency",
        "source": "Official/public",
        "note": "Pan-India emergency response number for police, fire and medical help.",
    },
    {
        "id": "emergency-108",
        "label": "Ambulance / emergency medical transport",
        "number": "108",
        "kind": "emergency",
        "source": "Official/public",
        "note": "Emergency ambulance service; availability can vary by state and location.",
    },
]


def _auth() -> Any:
    from . import auth
    return auth


def authenticated_user(request: Request) -> dict[str, Any]:
    return _auth().get_authenticated_user(request)


def committee_user(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    return _auth().require_committee(user)


def _defaults() -> dict[str, Any]:
    return {
        "residents": [], "ledger": [], "payments": [],
        "amcRates": copy.deepcopy(DEFAULT_AMC_RATES), "openingBalances": None,
        "expenseTypes": list(DEFAULT_EXPENSE_TYPES), "fixedDeposits": [], "events": [],
        "officeBearers": copy.deepcopy(DEFAULT_OFFICE_BEARERS), "tallyReconciliation": None,
    }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


def initialize_portal() -> None:
    """Idempotently create portal tables; never import a browser or Tally file."""
    with _auth().database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS portal_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS portal_collections (
                name TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS portal_payment_keys (
                resident_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                payment_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                PRIMARY KEY (resident_id, idempotency_key)
            );
            """
        )
        now = _auth().utc_now().isoformat()
        connection.execute("INSERT OR IGNORE INTO portal_state(id, revision, updated_at) VALUES (1, 0, ?)", (now,))
        for name, value in _defaults().items():
            connection.execute(
                "INSERT OR IGNORE INTO portal_collections(name, value_json, updated_at) VALUES (?, ?, ?)",
                (name, _json(value), now),
            )


def _invalid(label: str) -> HTTPException:
    # Pydantic's default error JSON includes input values, including passwords.
    # Never reflect validation inputs (or stringify ValidationError) here.
    return HTTPException(422, f"Invalid {label} data. Check field names, types, required values, dates and size limits.")


def _model(model: type[PortalModel], value: Any, label: str) -> PortalModel:
    try:
        return model.model_validate(value)
    except (ValidationError, ValueError, TypeError, OverflowError):
        raise _invalid(label) from None


def _identity_text(value: str) -> str:
    return unicodedata.normalize("NFKC", " ".join(value.split())).casefold()


def _row_key(name: str, row: Any) -> str:
    if name == "expenseTypes":
        return _identity_text(row)
    if name == "officeBearers":
        return _identity_text(row["name"])
    return row["financialYear"] if name == "amcRates" else row["id"]


def _format_amount(amount: float) -> str:
    whole, _, fractional = f"{amount:.2f}".partition(".")
    tail = whole[-3:]
    head = whole[:-3]
    groups: list[str] = []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    formatted = ",".join([*groups, tail])
    return "₹ " + formatted + ("." + fractional if fractional != "00" else "")


def _display_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{parsed.day:02d} {months[parsed.month - 1]} {parsed.year}"


def _collection(name: str, value: Any, *, deduplicate: bool = False) -> tuple[Any, dict[str, str]]:
    if name not in COLLECTION_NAMES:
        raise HTTPException(404, "Unknown portal collection.")
    passwords: dict[str, str] = {}
    if name in {"openingBalances", "tallyReconciliation"}:
        if value is None:
            return None, passwords
        cls = OpeningBalances if name == "openingBalances" else TallyReconciliation
        return json_record(_model(cls, value, name)), passwords
    if not isinstance(value, list) or len(value) > MAX_COLLECTION_ROWS:
        raise _invalid(name)
    rows: list[Any] = []
    seen: dict[str, Any] = {}
    for raw in value:
        if name == "expenseTypes":
            if not isinstance(raw, str) or not raw.strip() or len(raw) > 240:
                raise _invalid(name)
            row: Any = raw.strip()
        else:
            parsed = _model(ROW_MODELS[name], raw, name)
            if name == "residents" and parsed.password:
                passwords[parsed.id] = parsed.password
            row = json_record(parsed)
            if name == "payments":
                row["amount"] = _format_amount(row["numericAmount"])
                if not row["date"]:
                    row["date"] = _display_date(row["transactionDate"])
        key = _row_key(name, row)
        if key in seen:
            if deduplicate and seen[key] == row:
                continue
            raise HTTPException(422, f"Duplicate or conflicting identities in {name}.")
        seen[key] = row
        rows.append(row)
    if name == "residents":
        _validate_resident_uniqueness(rows)
    return rows, passwords


def _validate_resident_uniqueness(residents: list[dict[str, Any]]) -> None:
    houses: set[str] = set()
    mobiles: set[str] = set()
    for resident in residents:
        house = _identity_text(resident["house"])
        mobile = normalize_mobile(resident["mobile"])
        if house in houses or mobile in mobiles:
            raise HTTPException(422, "Each resident must have a unique house and registered phone number.")
        houses.add(house)
        mobiles.add(mobile)


def _load(connection: sqlite3.Connection) -> tuple[int, dict[str, Any]]:
    row = connection.execute("SELECT revision FROM portal_state WHERE id = 1").fetchone()
    if row is None:
        raise HTTPException(503, "Portal storage has not been initialized.")
    collections = _defaults()
    try:
        for saved in connection.execute("SELECT name, value_json FROM portal_collections"):
            if saved["name"] in COLLECTION_NAMES:
                collections[saved["name"]] = json.loads(saved["value_json"])
    except (json.JSONDecodeError, TypeError, ValueError):
        raise HTTPException(500, "Portal storage contains an unreadable collection.") from None
    return int(row["revision"]), collections


def _check_revision(actual: int, expected: int) -> None:
    if actual != expected:
        raise HTTPException(409, "Portal data changed. Refresh the portal and retry your change.")


def _save(connection: sqlite3.Connection, old: dict[str, Any], new: dict[str, Any], revision: int, *, force: bool = False) -> int:
    _validate_storage_limits(new)
    changed = [name for name in COLLECTION_NAMES if old[name] != new[name]]
    if not changed and not force:
        return revision
    now = _auth().utc_now().isoformat()
    cursor = connection.execute(
        "UPDATE portal_state SET revision = revision + 1, updated_at = ? WHERE id = 1 AND revision = ?",
        (now, revision),
    )
    if cursor.rowcount != 1:
        raise HTTPException(409, "Portal data changed. Refresh the portal and retry your change.")
    for name in changed:
        serialized = _json(new[name])
        if len(serialized.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise HTTPException(413, f"The {name} collection exceeds the storage size limit.")
        connection.execute(
            "UPDATE portal_collections SET value_json = ?, updated_at = ? WHERE name = ?",
            (serialized, now, name),
        )
    return revision + 1


def _actor(connection: sqlite3.Connection, user: dict[str, Any], *, committee: bool = False) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM users WHERE id = ? AND active = 1", (user["id"],)).fetchone()
    if row is None:
        raise HTTPException(401, "Your account is inactive. Sign in again.")
    if committee and row["role"] != "committee":
        raise HTTPException(403, "Committee access is required.")
    return row


def _resident_for_user(connection: sqlite3.Connection, collections: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    account = _actor(connection, user)
    if account["role"] != "resident":
        raise HTTPException(403, "Resident access is required.")
    if account["must_change_password"]:
        raise HTTPException(403, "Change your temporary password before entering the resident portal.")
    resident_id = account["resident_id"]
    resident = next((row for row in collections["residents"] if row["id"] == resident_id), None)
    if not resident or not resident["active"]:
        raise HTTPException(403, "This account is not linked to an active backend resident record.")
    return resident


def _public_resident(
    resident: dict[str, Any],
    account: sqlite3.Row | None,
    *,
    include_private: bool = False,
) -> dict[str, Any]:
    sanitized = json_record(_model(ROW_MODELS["residents"], resident, "stored resident"))
    if not include_private:
        # A resident snapshot may include the opted-in profession because it
        # is suitable for a public directory. The tenant/property-owner name
        # and an unconsented profession remain committee-only fields. The
        # consent bit itself is also committee-only metadata.
        if not sanitized.get("publicProfessionalListing"):
            sanitized.pop("profession", None)
        sanitized.pop("tenantOwnerName", None)
        sanitized.pop("publicProfessionalListing", None)
    sanitized["hasAccount"] = account is not None
    sanitized["tempPassword"] = bool(account is not None and account["must_change_password"])
    return sanitized


def _public_professional(resident: dict[str, Any]) -> dict[str, Any] | None:
    """Project only explicitly consented, active professional directory rows."""
    sanitized = json_record(_model(ROW_MODELS["residents"], resident, "stored resident"))
    if not sanitized.get("active") or not sanitized.get("publicProfessionalListing") or not sanitized.get("profession"):
        return None
    return {
        "name": sanitized["name"],
        "house": sanitized["house"],
        "profession": sanitized["profession"],
        "contact": sanitized["mobile"],
    }


def _public_contacts(office_bearers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return official numbers plus committee-published association contacts."""
    contacts = copy.deepcopy(OFFICIAL_PUBLIC_CONTACTS)
    for person in office_bearers:
        phone = str(person.get("phone") or "").strip()
        if not phone:
            continue
        role = str(person.get("role") or "Association contact")
        name = str(person.get("display") or person.get("name") or "")
        contacts.append({
            "id": "association-" + str(person.get("id") or person.get("name")),
            "label": role + (" — " + name if name else ""),
            "number": phone,
            "kind": "local",
            "source": "Association-maintained",
            "note": "Published by the APCLRWA committee; please confirm availability.",
        })
    return contacts


def _snapshot(connection: sqlite3.Connection, revision: int, collections: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    account = _actor(connection, user)
    accounts = {
        row["resident_id"]: row
        for row in connection.execute("SELECT id, resident_id, must_change_password FROM users WHERE role = 'resident'")
        if row["resident_id"] is not None
    }
    if account["role"] == "committee":
        visible = copy.deepcopy(collections)
        visible["residents"] = [
            _public_resident(row, accounts.get(row["id"]), include_private=True)
            for row in collections["residents"]
        ]
        current = None
    else:
        resident = _resident_for_user(connection, collections, user)
        resident_id = resident["id"]
        current = _public_resident(resident, accounts.get(resident_id), include_private=False)
        visible = {
            "residents": [current],
            "ledger": [row for row in collections["ledger"] if row.get("residentId") == resident_id and row["status"] == "Posted" and row["kind"] in RECEIPT_KINDS],
            "payments": [row for row in collections["payments"] if row.get("residentId") == resident_id],
            "amcRates": collections["amcRates"], "events": collections["events"], "officeBearers": collections["officeBearers"],
            "openingBalances": None, "expenseTypes": [], "fixedDeposits": [], "tallyReconciliation": None,
        }
    return {"revision": revision, "collections": visible, "currentResident": current}


def _validate_accounts(connection: sqlite3.Connection, residents: list[dict[str, Any]]) -> None:
    _validate_resident_uniqueness(residents)
    users = connection.execute("SELECT id, username, role, resident_id FROM users").fetchall()
    seen_resident_ids: set[str] = set()
    usernames: dict[str, list[sqlite3.Row]] = {}
    for user in users:
        if user["resident_id"] is not None:
            if user["role"] != "resident" or user["resident_id"] in seen_resident_ids:
                raise HTTPException(409, "Resident account links are ambiguous. Repair the account links before saving.")
            seen_resident_ids.add(user["resident_id"])
        existing = str(user["username"]).strip().casefold()
        try:
            phone = normalize_mobile(existing)
        except ValueError:
            phone = existing
        for key in {existing, phone}:
            usernames.setdefault(key, []).append(user)
    for resident in residents:
        username = resident["mobile"].strip().casefold()
        for user in usernames.get(username, []):
            if not (user["role"] == "resident" and user["resident_id"] == resident["id"]):
                raise HTTPException(409, "A resident phone number conflicts with another authentication account.")


def _sync_accounts(connection: sqlite3.Connection, residents: list[dict[str, Any]], passwords: dict[str, str], previous: list[dict[str, Any]]) -> bool:
    """Called only after validation, in the same transaction as the JSON write."""
    now = _auth().utc_now().isoformat()
    by_id = {row["id"]: row for row in residents}
    previous_by_id = {row["id"]: row for row in previous}
    accounts = connection.execute("SELECT * FROM users WHERE role = 'resident'").fetchall()
    linked = {row["resident_id"]: row for row in accounts if row["resident_id"] is not None}
    changed = False
    for account in accounts:
        resident = by_id.get(account["resident_id"])
        if resident is None:
            if account["resident_id"] not in previous_by_id:
                continue
            if account["active"]:
                connection.execute("UPDATE users SET active = 0 WHERE id = ?", (account["id"],))
                changed = True
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (account["id"],))
            continue
        username = resident["mobile"].strip().casefold()
        password = passwords.get(resident["id"])
        previous_resident = previous_by_id.get(resident["id"])
        # A blank edit or append-only migration must not reactivate a login
        # disabled independently in auth. Activation is an explicit directory
        # inactive->active change or a committee credential provisioning/reset.
        active = int(account["active"]) if resident["active"] else 0
        if resident["active"] and (password or (previous_resident and not previous_resident["active"])):
            active = 1
        if password or not active or account["username"] != username:
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (account["id"],))
        if (account["username"], account["display_name"], int(account["active"])) != (username, resident["name"], active):
            connection.execute("UPDATE users SET username = ?, display_name = ?, active = ? WHERE id = ?", (username, resident["name"], active, account["id"]))
            changed = True
        if password:
            salt = secrets.token_bytes(16)
            hashed = _auth().hash_password(password, salt)
            connection.execute("UPDATE users SET password_salt = ?, password_hash = ?, must_change_password = 1 WHERE id = ?", (salt, hashed, account["id"]))
            changed = True
    for resident in residents:
        password = passwords.get(resident["id"])
        if resident["id"] in linked or not password:
            continue
        salt = secrets.token_bytes(16)
        hashed = _auth().hash_password(password, salt)
        connection.execute(
            """INSERT INTO users(id, username, display_name, role, password_salt, password_hash,
                                  active, created_at, resident_id, must_change_password)
               VALUES (?, ?, ?, 'resident', ?, ?, ?, ?, ?, 1)""",
            ("USR-" + secrets.token_hex(16), resident["mobile"].strip().casefold(), resident["name"], salt, hashed, int(resident["active"]), now, resident["id"]),
        )
        changed = True
    return changed


def _bind_records(name: str, rows: list[dict[str, Any]], residents: list[dict[str, Any]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bind receipts to stable resident IDs once, never filter access by a phone/house."""
    by_id = {row["id"]: row for row in residents}
    by_house = {_identity_text(row["house"]): row for row in residents}
    by_mobile = {row["mobile"]: row for row in residents}
    previous = {row["id"]: row for row in existing}
    result = copy.deepcopy(rows)
    for row in result:
        old = previous.get(row["id"])
        unchanged_identity = old is not None and row.get("house", "") == old.get("house", "") and (name == "ledger" or row.get("mobile", "") == old.get("mobile", ""))
        if not row.get("residentId") and unchanged_identity and old.get("residentId"):
            row["residentId"] = old["residentId"]
        if name == "payments" and row.get("mobile"):
            try:
                row["mobile"] = normalize_mobile(row["mobile"])
            except ValueError:
                raise _invalid(name) from None
        resident_id = row.get("residentId")
        if resident_id:
            resident = by_id.get(resident_id)
            if resident is None:
                if unchanged_identity and old.get("residentId") == resident_id:
                    continue  # Retain a historical link after a resident is removed.
                raise HTTPException(422, "A financial record references an unknown resident ID.")
            if not (unchanged_identity and old.get("residentId") == resident_id):
                if row.get("house") and _identity_text(row["house"]) != _identity_text(resident["house"]):
                    raise HTTPException(422, "The resident ID and house on a financial record disagree.")
                if name == "payments" and row.get("mobile") and row["mobile"] != resident["mobile"]:
                    raise HTTPException(422, "The resident ID and phone on a payment disagree.")
        else:
            house_match = by_house.get(_identity_text(row.get("house") or ""))
            phone_match = by_mobile.get(row.get("mobile", "")) if name == "payments" else None
            if house_match and phone_match and house_match["id"] != phone_match["id"]:
                raise HTTPException(422, "A payment's house and phone identify different residents.")
            # An unchanged, previously unlinked historical record stays unlinked.
            # Adding a new resident with the same house must not grant old receipts.
            resident = None if unchanged_identity else phone_match or house_match
            if resident:
                if row.get("house") and _identity_text(row["house"]) != _identity_text(resident["house"]):
                    raise HTTPException(422, "A financial record's house disagrees with its registered resident.")
                if name == "payments" and row.get("mobile") and row["mobile"] != resident["mobile"]:
                    raise HTTPException(422, "A payment's phone disagrees with its registered resident.")
                row["residentId"] = resident["id"]
        if name == "payments" and resident:
            row["resident"] = row["resident"] or resident["name"]
            row["mobile"] = row["mobile"] or resident["mobile"]
            row["house"] = row["house"] or resident["house"]
    return result


def _fy_for(value: date) -> str:
    start = value.year if value.month >= 4 else value.year - 1
    return f"{start}–{str(start + 1)[-2:]}"


def _amc_fy(value: date) -> str:
    return f"{value.year}–{str(value.year + 1)[-2:]}" if value.month <= 3 else _fy_for(value)


def _transfer(advance: dict[str, Any]) -> dict[str, Any]:
    target = advance.get("amcForFinancialYear") or advance["financialYear"]
    start = int(target[:4])
    row = {
        "id": "AMC-XFER-" + advance["id"], "kind": "AMC Transfer", "amount": advance["amount"],
        "description": "Advance AMC transferred to AMC for FY " + target,
        "mode": "Non-cash reclassification", "date": f"{start}-04-01", "financialYear": target,
        "status": "Posted", "bucket": "AMC", "transferOf": advance["id"],
        "createdAt": datetime(start, 4, 1, tzinfo=KOLKATA).astimezone(timezone.utc).isoformat(),
    }
    for key in ("house", "residentId"):
        if key in advance:
            row[key] = advance[key]
    return json_record(_model(LedgerEntry, row, "AMC transfer"))


def _ensure_transfers(collections: dict[str, Any]) -> None:
    ledger = collections["ledger"]
    by_id = {row["id"]: row for row in ledger}
    linked: set[str] = set()
    today = _auth().utc_now().astimezone(KOLKATA).date()
    for transfer in [row for row in ledger if row["kind"] == "AMC Transfer"]:
        source_id = transfer["transferOf"]
        source = by_id.get(source_id)
        if source_id in linked or not source or source["kind"] != "Advance AMC" or source["status"] != "Posted":
            raise HTTPException(422, "AMC transfers must reference one posted advance exactly once.")
        expected = _transfer(source)
        fields = ("id", "amount", "house", "residentId", "mode", "date", "financialYear", "status", "bucket", "transferOf")
        if any(transfer.get(key) != expected.get(key) for key in fields):
            raise HTTPException(409, "An AMC transfer conflicts with its source advance. Resolve the source/transfer conflict before saving.")
        if today < date.fromisoformat(expected["date"]):
            raise HTTPException(422, "AMC advances cannot be reclassified before April 1 of the target financial year.")
        linked.add(source_id)
    additions = []
    for advance in ledger:
        if advance["kind"] != "Advance AMC" or advance["status"] != "Posted" or advance["id"] in linked:
            continue
        expected = _transfer(advance)
        if today < date.fromisoformat(expected["date"]):
            continue
        if expected["id"] in by_id:
            raise HTTPException(409, "An AMC transfer ID conflicts with an existing ledger record.")
        additions.append(expected)
        linked.add(advance["id"])
    ledger.extend(additions)


def _guard_ledger_update(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> None:
    before = {row["id"]: row for row in old}
    after = {row["id"]: row for row in new}
    for row in old:
        if row["kind"] == "AMC Transfer" or row.get("paymentId"):
            if after.get(row["id"]) != row:
                raise HTTPException(409, "Payment receipts and automatic AMC transfers must be preserved by general ledger edits.")
    for row in new:
        if (row["kind"] == "AMC Transfer" or row.get("paymentId")) and before.get(row["id"]) != row:
            raise HTTPException(422, "Payment receipts and AMC transfers are created by the server.")


def _guard_payment_update(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    before = {row["id"]: row for row in old}
    if set(before) != {row["id"] for row in new}:
        raise HTTPException(422, "Create payment claims through resident submission or explicit migration; claims cannot be deleted through collection replacement.")
    result = copy.deepcopy(new)
    mutable = {"transactionDate", "mode", "details", "date"}
    for row in result:
        previous = before[row["id"]]
        if row["status"] != previous["status"]:
            raise HTTPException(422, "Use the payment review endpoint to approve or reject a payment.")
        if any(row.get(key) != previous.get(key) for key in set(row) | set(previous) if key not in mutable):
            raise HTTPException(422, "Payment identity, amount, review fields and accounting fields cannot be changed through collection replacement.")
        if previous["status"] == "Approved" and row != previous:
            raise HTTPException(409, "Approved payment details are already posted and cannot be edited independently of their receipt.")
        row["date"] = _display_date(row["transactionDate"])
        if row["transactionDate"] != previous["transactionDate"]:
            parsed = date.fromisoformat(row["transactionDate"])
            if _fy_for(parsed) != row["financialYear"] or (row["type"] == "Maintenance" and (parsed.month > 3 or _amc_fy(parsed) != row.get("amcForFinancialYear"))):
                raise HTTPException(422, "A payment detail edit cannot move the claim to another financial year or AMC window.")
    return result


def _write_collection(name: str, payload: CollectionWrite, user: dict[str, Any]) -> dict[str, Any]:
    value, passwords = _collection(name, payload.value)
    with _auth().database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _actor(connection, user, committee=True)
        revision, old = _load(connection)
        _check_revision(revision, payload.revision)
        new = copy.deepcopy(old)
        if name in {"ledger", "payments"}:
            value = _bind_records(name, value, old["residents"], old[name])
        if name == "ledger":
            _guard_ledger_update(old[name], value)
        if name == "payments":
            value = _guard_payment_update(old[name], value)
        new[name] = value
        if name == "residents":
            _validate_accounts(connection, value)
        _ensure_transfers(new)
        account_changes = _sync_accounts(connection, value, passwords, old["residents"]) if name == "residents" else False
        revision = _save(connection, old, new, revision, force=account_changes)
        return _snapshot(connection, revision, new, user)


def _get_portal(user: dict[str, Any]) -> dict[str, Any]:
    with _auth().database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        actor = _actor(connection, user)
        revision, old = _load(connection)
        if actor["role"] == "resident":
            _resident_for_user(connection, old, user)
        new = copy.deepcopy(old)
        _ensure_transfers(new)
        revision = _save(connection, old, new, revision)
        return _snapshot(connection, revision, new, user)


def _amount_due(collections: dict[str, Any], resident: dict[str, Any], target_fy: str) -> float:
    rates = sorted(collections["amcRates"] or DEFAULT_AMC_RATES, key=lambda row: row["financialYear"])
    eligible = [row for row in rates if int(row["financialYear"][:4]) <= int(target_fy[:4])]
    rate = (eligible[-1] if eligible else rates[0])[resident["residentType"].lower()]
    transferred = {row["transferOf"] for row in collections["ledger"] if row["kind"] == "AMC Transfer" and row["status"] == "Posted"}
    paid = 0.0
    for row in collections["ledger"]:
        if row.get("residentId") != resident["id"] or row["status"] != "Posted":
            continue
        if row["kind"] in {"Maintenance", "AMC Transfer"} and row["financialYear"] == target_fy:
            paid += row["amount"]
        elif row["kind"] == "Advance AMC" and row["id"] not in transferred and (row.get("amcForFinancialYear") or row["financialYear"]) == target_fy:
            paid += row["amount"]
    return max(0.0, round(rate - paid, 2))


def _submit_payment(payload: ResidentPayment, user: dict[str, Any]) -> dict[str, Any]:
    fingerprint = hashlib.sha256(_json(payload.model_dump(exclude={"idempotencyKey"})).encode("utf-8")).hexdigest()
    with _auth().database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        revision, old = _load(connection)
        resident = _resident_for_user(connection, old, user)
        prior = connection.execute(
            "SELECT request_hash, payment_id FROM portal_payment_keys WHERE resident_id = ? AND idempotency_key = ?",
            (resident["id"], payload.idempotencyKey),
        ).fetchone()
        if prior:
            if prior["request_hash"] != fingerprint:
                raise HTTPException(409, "This idempotency key was already used for a different payment.")
            return _snapshot(connection, revision, old, user)
        now = _auth().utc_now()
        today = now.astimezone(KOLKATA).date()
        target_fy = _amc_fy(today)
        if payload.type == "Maintenance":
            if today.month > 3:
                raise HTTPException(422, "Resident AMC payment claims are accepted only from January 1 through March 31.")
            if resident["residentType"] not in {"Owner", "Tenant"}:
                raise HTTPException(422, "The committee must set your owner or tenant status before AMC payment.")
            due = _amount_due(old, resident, target_fy)
            if due <= 0 or abs(payload.numericAmount - due) > 0.005:
                raise HTTPException(422, "The AMC claim amount must match this resident's outstanding AMC charge.")
        if payload.type == "Membership" and (resident["initialChargePaid"] or payload.numericAmount != 500):
            raise HTTPException(422, "Membership claims must be for the unpaid one-time charge of 500.")
        if payload.type in {"Maintenance", "Membership"}:
            pending = [row for row in old["payments"] if row.get("residentId") == resident["id"] and row["type"] == payload.type and row["status"] == "Pending verification"]
            if any(payload.type == "Membership" or row.get("amcForFinancialYear", row["financialYear"]) == target_fy for row in pending):
                raise HTTPException(409, "A claim for this charge is already awaiting committee verification.")
        claim: dict[str, Any] = {
            "id": "PAY-" + secrets.token_hex(16), "residentId": resident["id"], "resident": resident["name"],
            "mobile": resident["mobile"], "house": resident["house"], "type": payload.type,
            "numericAmount": payload.numericAmount, "amount": _format_amount(payload.numericAmount),
            "date": _display_date(today.isoformat()), "transactionDate": today.isoformat(), "createdAt": now.isoformat(),
            "financialYear": _fy_for(today), "status": "Pending verification", "mode": payload.mode, "details": payload.details,
        }
        if payload.type == "Maintenance":
            claim.update(amcForFinancialYear=target_fy, amcBucket="Advance AMC")
        claim = json_record(_model(PaymentRecord, claim, "payment"))
        new = copy.deepcopy(old)
        new["payments"].append(claim)
        _ensure_transfers(new)
        connection.execute(
            "INSERT INTO portal_payment_keys(resident_id, idempotency_key, request_hash, payment_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (resident["id"], payload.idempotencyKey, fingerprint, claim["id"], now.isoformat()),
        )
        revision = _save(connection, old, new, revision)
        return _snapshot(connection, revision, new, user)


def _posted_receipt(claim: dict[str, Any], now: str) -> dict[str, Any]:
    maintenance = claim["type"] == "Maintenance"
    membership = claim["type"] == "Membership"
    prefix = "REC-" if maintenance else "MEM-" if membership else "DON-"
    row = {
        "id": prefix + claim["id"], "paymentId": claim["id"],
        "kind": ("Advance AMC" if claim.get("amcBucket") == "Advance AMC" else "Maintenance") if maintenance else "Membership" if membership else "Collections",
        "amount": claim["numericAmount"], "house": claim["house"], "description": claim["details"],
        "mode": claim["mode"], "date": claim["transactionDate"], "financialYear": claim["financialYear"],
        "status": "Posted", "createdAt": claim.get("createdAt") or now,
    }
    if claim.get("residentId"):
        row["residentId"] = claim["residentId"]
    if maintenance:
        row.update(amcForFinancialYear=claim.get("amcForFinancialYear") or claim["financialYear"], bucket=claim.get("amcBucket") or "AMC")
    elif not membership:
        row.update(donorName=claim.get("donorName") or claim["resident"] or "Donor", donationType=claim.get("donationType") or "Ganesha Festival")
    return json_record(_model(LedgerEntry, row, "posted receipt"))


def _review_payment(payment_id: str, payload: PaymentReview, user: dict[str, Any]) -> dict[str, Any]:
    with _auth().database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        actor = _actor(connection, user, committee=True)
        revision, old = _load(connection)
        _check_revision(revision, payload.revision)
        new = copy.deepcopy(old)
        claim = next((row for row in new["payments"] if row["id"] == payment_id), None)
        if claim is None:
            raise HTTPException(404, "The payment claim was not found.")
        if claim["status"] == payload.status:
            return _snapshot(connection, revision, old, user)
        if claim["status"] != "Pending verification":
            raise HTTPException(409, "This payment has already been reviewed.")
        now = _auth().utc_now().isoformat()
        if payload.status == "Approved":
            if claim["type"] == "Membership":
                resident = next((row for row in new["residents"] if row["id"] == claim.get("residentId")), None)
                if not resident or claim["numericAmount"] != 500:
                    raise HTTPException(422, "Membership approval requires a valid linked resident and a charge of 500.")
                details = {"date": claim["transactionDate"], "mode": claim["mode"], "details": claim["details"]}
                if resident["initialChargePaid"] and resident.get("membershipPayment") != details:
                    raise HTTPException(409, "The one-time membership charge is already recorded as paid with different payment details.")
                resident.update(initialChargePaid=True, membershipPayment=details)
                receipt = _posted_receipt(claim, now)
                existing = next((row for row in new["ledger"] if row.get("kind") == "Membership" and row.get("status") == "Posted" and row.get("residentId") == resident["id"] and row.get("amount") == receipt["amount"] and row.get("date") == receipt["date"]), None)
                if existing is None:
                    new["ledger"].append(receipt)
                    existing = receipt
                claim["ledgerId"] = existing["id"]
            else:
                if claim["type"] == "Maintenance" and not any(row["id"] == claim.get("residentId") for row in new["residents"]):
                    raise HTTPException(422, "Maintenance approval requires a valid linked resident.")
                receipt = _posted_receipt(claim, now)
                existing = next((row for row in new["ledger"] if row["id"] == receipt["id"]), None)
                if existing:
                    # A legacy import can already contain this exact receipt.
                    # Review never silently overwrites or double-posts it.
                    comparable = dict(existing)
                    comparable.setdefault("paymentId", claim["id"])
                    if comparable != receipt:
                        raise HTTPException(409, "This claim's receipt ID conflicts with an existing ledger record.")
                    existing["paymentId"] = claim["id"]
                else:
                    new["ledger"].append(receipt)
                claim["ledgerId"] = receipt["id"]
        claim.update(status=payload.status, reviewedAt=now, reviewedBy=actor["username"])
        _ensure_transfers(new)
        revision = _save(connection, old, new, revision)
        return _snapshot(connection, revision, new, user)


def _strip_legacy_secrets(value: Any, depth: int = 0) -> tuple[Any, bool]:
    if depth > 20:
        raise _invalid("migration")
    removed = False
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z]", "", key.casefold())
            if "password" in normalized or normalized in {
                "passwd", "pwd", "salt", "hash", "token", "accesstoken", "refreshtoken",
                "sessiontoken", "sessioncookie", "cookie", "secret", "hasaccount",
            }:
                removed = True
                continue
            clean[key], nested_removed = _strip_legacy_secrets(item, depth + 1)
            removed = removed or nested_removed
        return clean, removed
    if isinstance(value, list):
        clean_list = []
        for item in value:
            clean_item, nested_removed = _strip_legacy_secrets(item, depth + 1)
            clean_list.append(clean_item)
            removed = removed or nested_removed
        return clean_list, removed
    return value, False


def _legacy_date(row: dict[str, Any]) -> str:
    for value in (row.get("transactionDate"), row.get("date"), str(row.get("createdAt") or "")[:10]):
        if not isinstance(value, str) or not value:
            continue
        try:
            return iso_date(value)
        except ValueError:
            pass
        for fmt in ("%d %b %Y", "%d %B %Y", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d %b, %Y"):
            try:
                return datetime.strptime(value.replace(",", "").strip(), fmt.replace(",", "")).date().isoformat()
            except ValueError:
                pass
    raise _invalid("legacy payment date")


def _normalize_legacy(name: str, value: Any, warnings: list[str]) -> Any:
    if name not in {"residents", "payments", "ledger"} or not isinstance(value, list):
        return value
    result = []
    for raw in value:
        if not isinstance(raw, dict):
            raise _invalid(name)
        row = copy.deepcopy(raw)
        if name == "residents":
            if row.get("cross") is None:
                row["cross"] = ""
            if row.get("residentType") is not None and not isinstance(row["residentType"], str):
                raise _invalid(name)
            if row.get("residentType") not in ("Owner", "Tenant", "Unspecified"):
                row["residentType"] = "Unspecified"
                warnings.append("Legacy residents with missing owner/tenant classification use Unspecified; set their type before AMC collection.")
            row.setdefault("active", True)
            row.setdefault("initialCharge", 500)
            row.setdefault("initialChargePaid", False)
            row.setdefault("createdAt", "")
            if row.get("initialChargePaid") and not row.get("membershipPayment"):
                row["initialChargePaid"] = False
                warnings.append("Legacy membership paid flags without supporting payment details remain unverified.")
        elif name == "payments":
            # Browser review assertions are not backend verification. Imported
            # claims are never auto-posted or made Approved by this endpoint.
            for field in ("status", "mode", "details", "date", "transactionDate", "createdAt", "financialYear", "amcForFinancialYear", "amcBucket"):
                if row.get(field) is not None and not isinstance(row[field], str):
                    raise _invalid(name)
            if row.get("status") not in (None, "Pending verification", "Rejected"):
                warnings.append("Legacy payment approval/posting assertions were reset to Pending verification; the committee must review those claims.")
            row["status"] = "Rejected" if row.get("status") == "Rejected" else "Pending verification"
            for field in ("reviewedBy", "reviewedAt", "ledgerId"):
                row.pop(field, None)
            try:
                row["numericAmount"] = finite_legacy_amount(row.get("numericAmount", row.get("amount")))
            except (ValueError, TypeError, OverflowError):
                raise _invalid("legacy payment amount") from None
            row["transactionDate"] = _legacy_date(row)
            parsed_date = date.fromisoformat(row["transactionDate"])
            row["date"] = _display_date(row["transactionDate"])
            row["amount"] = _format_amount(row["numericAmount"])
            row["financialYear"] = row.get("financialYear") or _fy_for(parsed_date)
            if row.get("type") == "Maintenance":
                row["amcForFinancialYear"] = row.get("amcForFinancialYear") or _amc_fy(parsed_date)
                row["amcBucket"] = row.get("amcBucket") or ("Advance AMC" if parsed_date.month <= 3 else "AMC")
            row["mode"] = row.get("mode") or "UPI"
            row["details"] = row.get("details") or "Legacy payment claim; verify the supporting transaction."
        elif row.get("kind") == "AMC Transfer":
            row.setdefault("bucket", "AMC")
        result.append(row)
    return result


def _merge_append(name: str, existing: Any, incoming: Any, warnings: list[str]) -> Any:
    if name in {"openingBalances", "tallyReconciliation"}:
        if incoming is None:
            return copy.deepcopy(existing)
        if existing is None:
            return copy.deepcopy(incoming)
        if existing != incoming:
            raise HTTPException(409, f"The imported {name} conflicts with existing data; import never replaces existing records.")
        warnings.append(f"Existing {name} already matches and will be skipped.")
        return copy.deepcopy(existing)
    result = copy.deepcopy(existing)
    indexed = {_row_key(name, row): row for row in existing}
    skipped = 0
    for row in incoming:
        key = _row_key(name, row)
        if key in indexed:
            if indexed[key] != row:
                raise HTTPException(409, f"An imported {name} identity conflicts with an existing record; import never overwrites records.")
            skipped += 1
        else:
            result.append(copy.deepcopy(row))
            indexed[key] = row
    if skipped:
        warnings.append(f"{skipped} existing {name} record(s) already match and will be skipped.")
    if len(result) > MAX_COLLECTION_ROWS:
        raise HTTPException(413, f"The merged {name} collection exceeds the record limit.")
    return result


def _prepare_migration(connection: sqlite3.Connection, existing: dict[str, Any], raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int], list[str]]:
    if any(name not in COLLECTION_NAMES for name in raw):
        raise HTTPException(422, "Migration contains an unknown collection name.")
    clean, removed = _strip_legacy_secrets(raw)
    warnings: list[str] = []
    if removed:
        warnings.append("Legacy passwords and account secrets were discarded; no legacy credential is imported.")
    normalized: dict[str, Any] = {}
    counts: dict[str, int] = {}
    for name, value in clean.items():
        value = _normalize_legacy(name, value, warnings)
        normalized[name], _ = _collection(name, value, deduplicate=True)
        counts[name] = len(normalized[name]) if isinstance(normalized[name], list) else int(normalized[name] is not None)
        if isinstance(value, list) and len(value) != counts[name]:
            warnings.append(f"Equal duplicate identities within imported {name} were deduplicated.")
    merged = copy.deepcopy(existing)
    if "residents" in normalized:
        merged["residents"] = _merge_append("residents", existing["residents"], normalized["residents"], warnings)
    _validate_accounts(connection, merged["residents"])
    for name, value in normalized.items():
        if name == "residents":
            continue
        if name in {"ledger", "payments"}:
            value = _bind_records(name, value, merged["residents"], existing[name])
            normalized[name] = value
        merged[name] = _merge_append(name, existing[name], value, warnings)
    if normalized.get("residents"):
        warnings.append("Resident accounts are not provisioned by migration. Residents without an existing backend account need a committee-set temporary password (at least 12 characters).")
    if any(not row.get("residentId") for row in normalized.get("payments", [])):
        warnings.append("Some legacy claims could not be linked to a resident. They are committee-only and cannot approve membership or AMC without a valid resident link.")
    _ensure_transfers(merged)
    # Validate storage bounds before backup, account changes, or collection writes.
    _validate_storage_limits(merged)
    return merged, counts, list(dict.fromkeys(warnings))


def _validate_storage_limits(collections: dict[str, Any]) -> None:
    for name in COLLECTION_NAMES:
        value = collections[name]
        if isinstance(value, list) and len(value) > MAX_COLLECTION_ROWS:
            raise HTTPException(413, f"The {name} collection exceeds the record limit.")
        if len(_json(value).encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise HTTPException(413, f"The {name} collection exceeds the storage size limit.")


def _private_backup() -> None:
    """Copy the committed pre-import DB while the caller holds BEGIN IMMEDIATE.

    A separate read connection is important: backing up from the connection
    holding a write transaction can block indefinitely. The writer reservation
    keeps the committed source stable until this backup and import finish.
    The backup contains password hashes, never a JSON credential export.
    """
    directory = Path(_auth().DATA_DIR) / "backups"
    destination: Path | None = None
    source: sqlite3.Connection | None = None
    target: sqlite3.Connection | None = None
    try:
        if directory.is_symlink():
            raise OSError("Backup directory must not be a symlink.")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        stamp = _auth().utc_now().strftime("%Y%m%dT%H%M%SZ")
        destination = directory / f"portal-before-import-{stamp}-{secrets.token_hex(8)}.sqlite3"
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        os.chmod(destination, 0o600)
        source = sqlite3.connect(_auth().DATABASE_PATH, timeout=10)
        source.execute("PRAGMA query_only = ON")
        target = sqlite3.connect(destination, timeout=10)
        source.backup(target)
        target.close()
        target = None
        source.close()
        source = None
    except (OSError, sqlite3.Error):
        if target is not None:
            target.close()
        if source is not None:
            source.close()
        if destination is not None:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
        raise HTTPException(503, "A private pre-import database backup could not be created. No import was applied.") from None


def _preview_migration(payload: MigrationPreview, user: dict[str, Any]) -> dict[str, Any]:
    with _auth().database() as connection:
        connection.execute("BEGIN")
        _actor(connection, user, committee=True)
        revision, existing = _load(connection)
        _, counts, warnings = _prepare_migration(connection, existing, payload.collections)
        return {"counts": counts, "warnings": warnings, "revision": revision}


def _import_migration(payload: MigrationImport, user: dict[str, Any]) -> dict[str, Any]:
    with _auth().database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _actor(connection, user, committee=True)
        revision, existing = _load(connection)
        _check_revision(revision, payload.revision)
        merged, _, _ = _prepare_migration(connection, existing, payload.collections)
        _private_backup()
        accounts_changed = _sync_accounts(connection, merged["residents"], {}, existing["residents"])
        revision = _save(connection, existing, merged, revision, force=accounts_changed)
        return _snapshot(connection, revision, merged, user)


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


def _apply_tally(payload: RevisionRequest, user: dict[str, Any]) -> dict[str, Any]:
    import_path = Path(_auth().DATA_DIR) / "tally-import.json"
    try:
        with import_path.open("rb") as handle:
            raw = handle.read(MAX_PAYLOAD_BYTES + 1)
    except FileNotFoundError:
        raise HTTPException(404, "No local Tally import is available.") from None
    except OSError:
        raise HTTPException(503, "The local Tally import could not be read.") from None
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise HTTPException(413, "The local Tally import exceeds the payload limit.")
    clean, _ = _strip_legacy_secrets(_decode_json(raw))
    snapshot = _model(TallyImport, clean, "Tally import")
    ledger, _ = _collection("ledger", [json_record(row) for row in snapshot.transactions], deduplicate=True)
    if any(row["status"] != "Posted" or row.get("paymentId") for row in ledger):
        raise HTTPException(422, "The Tally snapshot must contain posted book entries, not payment claims or server-managed payment receipts.")
    with _auth().database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _actor(connection, user, committee=True)
        revision, existing = _load(connection)
        _check_revision(revision, payload.revision)
        new = copy.deepcopy(existing)
        ledger = _bind_records("ledger", ledger, existing["residents"], existing["ledger"])
        new["ledger"] = _merge_append("ledger", existing["ledger"], ledger, [])
        if new["openingBalances"] is None and snapshot.openingBalances is not None:
            new["openingBalances"] = json_record(snapshot.openingBalances)
        metadata = json_record(snapshot.reconciliation)
        metadata.update(importId=snapshot.importId, sourceFiles=list(snapshot.sourceFiles), transactionCount=len(ledger))
        prior = copy.deepcopy(existing["tallyReconciliation"])
        if prior:
            prior.pop("importedAt", None)
        comparison = copy.deepcopy(metadata)
        comparison.pop("importedAt", None)
        metadata["importedAt"] = existing["tallyReconciliation"]["importedAt"] if prior == comparison and existing["tallyReconciliation"].get("importedAt") else _auth().utc_now().isoformat()
        new["tallyReconciliation"] = json_record(_model(TallyReconciliation, metadata, "Tally reconciliation"))
        _ensure_transfers(new)
        _validate_storage_limits(new)
        _private_backup()
        revision = _save(connection, existing, new, revision)
        return _snapshot(connection, revision, new, user)


async def _body(request: Request, model: type[PortalModel], *, limit: int = MAX_PAYLOAD_BYTES) -> PortalModel:
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
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, "The request exceeds the payload limit.")
        chunks.append(chunk)
    return _model(model, _decode_json(b"".join(chunks)), "request")


@router.get("/api/public/content")
def public_content(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    with _auth().database() as connection:
        connection.execute("BEGIN")
        _, collections = _load(connection)
        professionals = []
        for resident in collections["residents"]:
            listing = _public_professional(resident)
            if listing is not None:
                professionals.append(listing)
        return {
            "events": [row for row in collections["events"] if not row.get("residentsOnly", False)],
            "officeBearers": collections["officeBearers"],
            "professionals": professionals,
            "contacts": _public_contacts(collections["officeBearers"]),
        }


@router.get("/api/portal")
def portal_snapshot(response: Response, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return _get_portal(user)


@router.post("/api/admin/collections/{name}")
async def replace_collection(name: str, request: Request, response: Response, user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    payload = await _body(request, CollectionWrite)
    return await run_in_threadpool(_write_collection, name, payload, user)


@router.post("/api/resident/payments")
async def submit_resident_payment(request: Request, response: Response, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    payload = await _body(request, ResidentPayment, limit=32 * 1024)
    return await run_in_threadpool(_submit_payment, payload, user)


@router.post("/api/admin/payments/{payment_id}/review")
async def review_payment(payment_id: str, request: Request, response: Response, user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    payload = await _body(request, PaymentReview, limit=4096)
    return await run_in_threadpool(_review_payment, payment_id, payload, user)


@router.post("/api/admin/migration/preview")
async def preview_migration(request: Request, response: Response, user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    payload = await _body(request, MigrationPreview)
    return await run_in_threadpool(_preview_migration, payload, user)


@router.post("/api/admin/migration/import")
async def import_migration(request: Request, response: Response, user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    payload = await _body(request, MigrationImport)
    return await run_in_threadpool(_import_migration, payload, user)


@router.post("/api/admin/tally-import/apply")
async def apply_tally_import(request: Request, response: Response, user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    payload = await _body(request, RevisionRequest, limit=4096)
    return await run_in_threadpool(_apply_tally, payload, user)
