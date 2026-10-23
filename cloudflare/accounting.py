"""Portable normalized accounting operations for the Cloudflare D1 adapter.

The Worker keeps the imported Tally snapshot in its existing portal collection
store. These operations use the normalized D1 accounting tables created by
``migrations/0003_accounting.sql`` and never translate historical Tally rows
into journals.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date
from typing import Any, Iterable

from fastapi import HTTPException

try:
    from .d1 import D1Conflict, D1Error, D1Store
    from .portal_models import (
        AccountCreate,
        AccountingPeriodCreate,
        JournalCorrectionRequest,
        JournalEntryCreate,
        JournalLineInput,
        JournalPostRequest,
        JournalReversalRequest,
        PeriodActionRequest,
        JournalEntryRecord,
        financial_year_for_date,
        json_record,
    )
except ImportError:
    from d1 import D1Conflict, D1Error, D1Store
    from portal_models import (
    AccountCreate,
    AccountingPeriodCreate,
    JournalCorrectionRequest,
    JournalEntryCreate,
    JournalLineInput,
    JournalPostRequest,
    JournalReversalRequest,
    PeriodActionRequest,
    JournalEntryRecord,
    financial_year_for_date,
    json_record,
    )


DEFAULT_ACCOUNTS = (
    ("COA-BANK", "1000", "Bank", "Asset"),
    ("COA-CASH", "1010", "Cash", "Asset"),
    ("COA-FD", "1020", "Fixed Deposits", "Asset"),
    ("COA-RECEIVABLES", "1100", "Resident Receivables", "Asset"),
    ("COA-PAYABLES", "2000", "Payables", "Liability"),
    ("COA-CORPUS", "3000", "Association Corpus", "Equity"),
    ("COA-OPENING", "3100", "Opening Balance Equity", "Equity"),
    ("COA-MAINTENANCE", "4000", "Maintenance Income", "Income"),
    ("COA-MEMBERSHIP", "4010", "Membership Income", "Income"),
    ("COA-CONTRIBUTIONS", "4020", "Contributions and Donations", "Income"),
    ("COA-INTEREST", "4030", "Interest Income", "Income"),
    ("COA-EXPENSES", "5000", "Operating Expenses", "Expense"),
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _id(prefix: str, source: str | None = None) -> str:
    if source:
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]
        return f"{prefix}-{digest}-{secrets.token_hex(6)}"
    return f"{prefix}-{secrets.token_hex(12)}"


def _db_conflict(error: D1Conflict) -> HTTPException:
    text = str(error).casefold()
    if "closed" in text:
        return HTTPException(409, "The accounting period is closed.")
    if "immutable" in text:
        return HTTPException(409, "Posted journal entries are immutable; use a reversal or correction.")
    if "unique" in text or "constraint" in text:
        return HTTPException(409, "The accounting identity already exists or conflicts with another write.")
    return HTTPException(409, "The accounting data changed. Refresh and retry.")


def _account(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "accountType": row["account_type"],
        "parentId": row.get("parent_id"),
        "active": bool(row["active"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _period(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "financialYear": row["financial_year"],
        "startDate": row["start_date"],
        "endDate": row["end_date"],
        "status": row["status"],
        "closedAt": row.get("closed_at"),
        "closedBy": row.get("closed_by"),
        "closeReason": row.get("close_reason"),
        "closeAuthorization": row.get("close_authorization"),
        "reopenedAt": row.get("reopened_at"),
        "reopenedBy": row.get("reopened_by"),
        "reopenReason": row.get("reopen_reason"),
        "reopenAuthorization": row.get("reopen_authorization"),
        "createdAt": row["created_at"],
    }


def _audit(row: dict[str, Any]) -> dict[str, Any]:
    try:
        details = json.loads(row.get("details_json") or "{}")
    except (TypeError, ValueError):
        details = {}
    return {
        "id": row["id"],
        "occurredAt": row["occurred_at"],
        "actorUserId": row["actor_user_id"],
        "actorUsername": row["actor_username"],
        "action": row["action"],
        "entityType": row["entity_type"],
        "entityId": row["entity_id"],
        "financialYear": row.get("financial_year"),
        "periodId": row.get("period_id"),
        "reason": row.get("reason"),
        "authorization": row.get("authorization"),
        "details": details,
    }


def _audit_statement(
    actor: dict[str, Any],
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    now: str,
    financial_year: str | None = None,
    period_id: str | None = None,
    reason: str | None = None,
    authorization: str | None = None,
    details: dict[str, Any] | None = None,
) -> tuple[str, tuple[Any, ...]]:
    return (
        """INSERT INTO audit_events(
               id, occurred_at, actor_user_id, actor_username, action, entity_type,
               entity_id, financial_year, period_id, reason, authorization, details_json
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            _id("AUD"), now, actor["id"], actor["username"], action, entity_type,
            entity_id, financial_year, period_id, reason, authorization, _json(details or {}),
        ),
    )


async def _actor(store: D1Store, user: dict[str, Any]) -> dict[str, Any]:
    row = await store.first("SELECT * FROM users WHERE id = ? AND active = 1", user["id"])
    if row is None or row.get("role") != "committee":
        raise HTTPException(403, "Committee access is required.")
    return row


async def _commit(store: D1Store, statements: list[tuple[str, tuple[Any, ...]]]) -> None:
    try:
        await store.batch(statements)
    except D1Conflict as error:
        raise _db_conflict(error) from None


async def list_accounts(store: D1Store) -> list[dict[str, Any]]:
    return [_account(row) for row in await store.all("SELECT * FROM accounts ORDER BY code, id")]


async def create_account(store: D1Store, payload: AccountCreate, user: dict[str, Any], now: str) -> dict[str, Any]:
    actor = await _actor(store, user)
    account_id = payload.id or _id("COA")
    if payload.parentId == account_id:
        raise HTTPException(422, "An account cannot be its own parent.")
    if payload.parentId:
        parent = await store.first("SELECT id, active FROM accounts WHERE id = ?", payload.parentId)
        if parent is None:
            raise HTTPException(422, "The parent account does not exist.")
        if not parent.get("active"):
            raise HTTPException(422, "The parent account is inactive.")
    statements = [
        (
            """INSERT INTO accounts(id, code, name, account_type, parent_id, active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (account_id, payload.code, payload.name, payload.accountType, payload.parentId, int(payload.active), now, now),
        ),
        _audit_statement(
            actor, action="account.created", entity_type="account", entity_id=account_id, now=now,
            details={"code": payload.code, "accountType": payload.accountType},
        ),
    ]
    await _commit(store, statements)
    row = await store.first("SELECT * FROM accounts WHERE id = ?", account_id)
    if row is None:
        raise D1Error("The new account could not be read after creation.")
    return _account(row)


def _period_id(payload: AccountingPeriodCreate) -> str:
    if payload.id:
        return payload.id
    start_year = int(payload.financialYear[:4])
    return f"FY-{start_year}-{str(start_year + 1)[-2:]}"


async def create_period(store: D1Store, payload: AccountingPeriodCreate, user: dict[str, Any], now: str) -> dict[str, Any]:
    actor = await _actor(store, user)
    period_id = _period_id(payload)
    existing = await store.first("SELECT * FROM accounting_periods WHERE id = ?", period_id)
    if existing is not None:
        if (existing["financial_year"], existing["start_date"], existing["end_date"]) != (payload.financialYear, payload.startDate, payload.endDate):
            raise HTTPException(409, "The accounting period ID conflicts with existing period data.")
        return _period(existing)
    statements = [
        (
            """INSERT INTO accounting_periods(id, financial_year, start_date, end_date, status, created_at)
               VALUES (?, ?, ?, ?, 'Open', ?)""",
            (period_id, payload.financialYear, payload.startDate, payload.endDate, now),
        ),
        _audit_statement(
            actor, action="period.created", entity_type="accounting_period", entity_id=period_id, now=now,
            financial_year=payload.financialYear, period_id=period_id, details={"automatic": False},
        ),
    ]
    await _commit(store, statements)
    row = await store.first("SELECT * FROM accounting_periods WHERE id = ?", period_id)
    if row is None:
        raise D1Error("The new accounting period could not be read after creation.")
    return _period(row)


async def list_periods(store: D1Store) -> list[dict[str, Any]]:
    return [_period(row) for row in await store.all("SELECT * FROM accounting_periods ORDER BY start_date DESC, id")]


async def _period_for_entry(
    store: D1Store,
    *,
    entry_date: str,
    financial_year: str,
    period_id: str | None,
    actor: dict[str, Any],
    now: str,
) -> tuple[dict[str, Any], list[tuple[str, tuple[Any, ...]]]]:
    parsed = date.fromisoformat(entry_date)
    if financial_year_for_date(parsed) != financial_year:
        raise HTTPException(422, "The journal date and financial year do not match.")
    if period_id:
        row = await store.first("SELECT * FROM accounting_periods WHERE id = ?", period_id)
        if row is None:
            raise HTTPException(404, "The accounting period was not found.")
        if row["financial_year"] != financial_year or not row["start_date"] <= entry_date <= row["end_date"]:
            raise HTTPException(422, "The journal date is outside the selected accounting period.")
        return row, []
    row = await store.first("SELECT * FROM accounting_periods WHERE financial_year = ? ORDER BY start_date LIMIT 1", financial_year)
    if row is not None:
        if not row["start_date"] <= entry_date <= row["end_date"]:
            raise HTTPException(422, "The journal date is outside the accounting period.")
        return row, []
    start_year = int(financial_year[:4])
    period = {
        "id": f"FY-{start_year}-{str(start_year + 1)[-2:]}",
        "financial_year": financial_year,
        "start_date": f"{start_year}-04-01",
        "end_date": f"{start_year + 1}-03-31",
        "status": "Open",
        "closed_at": None,
        "closed_by": None,
        "close_reason": None,
        "close_authorization": None,
        "reopened_at": None,
        "reopened_by": None,
        "reopen_reason": None,
        "reopen_authorization": None,
        "created_at": now,
    }
    statements = [
        (
            """INSERT INTO accounting_periods(id, financial_year, start_date, end_date, status, created_at)
               VALUES (?, ?, ?, ?, 'Open', ?)""",
            (period["id"], period["financial_year"], period["start_date"], period["end_date"], now),
        ),
        _audit_statement(
            actor, action="period.created", entity_type="accounting_period", entity_id=period["id"], now=now,
            financial_year=financial_year, period_id=period["id"], details={"automatic": True, "reason": "Created for a journal entry."},
        ),
    ]
    return period, statements


def _assert_open(period: dict[str, Any]) -> None:
    if period["status"] != "Open":
        raise HTTPException(409, "The accounting period is closed.")


async def _validate_lines(store: D1Store, lines: Iterable[JournalLineInput | dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    normalized: list[dict[str, Any]] = []
    debit_total = 0
    credit_total = 0
    for index, line in enumerate(lines, start=1):
        value = line if isinstance(line, dict) else line.model_dump()
        account = await store.first("SELECT id, code, name, active FROM accounts WHERE id = ?", value["accountId"])
        if account is None:
            raise HTTPException(422, f"Unknown chart-of-accounts ID: {value['accountId']}.")
        if not account.get("active"):
            raise HTTPException(422, f"The chart-of-accounts ID is inactive: {value['accountId']}.")
        debit = value["debitPaise"]
        credit = value["creditPaise"]
        if (debit > 0) == (credit > 0):
            raise HTTPException(422, "Each journal line must contain either a debit or a credit.")
        normalized.append({
            "lineNo": index,
            "accountId": value["accountId"],
            "accountCode": account["code"],
            "accountName": account["name"],
            "description": value.get("description"),
            "debitPaise": debit,
            "creditPaise": credit,
        })
        debit_total += debit
        credit_total += credit
    if len(normalized) < 2:
        raise HTTPException(422, "A journal entry must contain at least two lines.")
    if debit_total != credit_total:
        raise HTTPException(422, "Journal debits and credits must balance in paise.")
    return normalized, debit_total


async def _entry_record(store: D1Store, entry_id: str) -> dict[str, Any]:
    row = await store.first("SELECT * FROM journal_entries WHERE id = ?", entry_id)
    if row is None:
        raise HTTPException(404, "The journal entry was not found.")
    lines = [
        {
            "id": line["id"],
            "lineNo": line["line_no"],
            "accountId": line["account_id"],
            "accountCode": line["code"],
            "accountName": line["name"],
            "description": line.get("description"),
            "debitPaise": line["debit_paise"],
            "creditPaise": line["credit_paise"],
        }
        for line in await store.all(
            """SELECT l.*, a.code, a.name FROM journal_lines l
               JOIN accounts a ON a.id = l.account_id
               WHERE l.entry_id = ? ORDER BY l.line_no""",
            entry_id,
        )
    ]
    value = {
        "id": row["id"],
        "date": row["entry_date"],
        "financialYear": row["financial_year"],
        "periodId": row["period_id"],
        "description": row["description"],
        "status": row["status"],
        "sourceType": row.get("source_type"),
        "sourceId": row.get("source_id"),
        "reversalOfEntryId": row.get("reversal_of_entry_id"),
        "correctionOfEntryId": row.get("correction_of_entry_id"),
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
        "postedBy": row.get("posted_by"),
        "postedAt": row.get("posted_at"),
        "lines": lines,
    }
    try:
        return json_record(JournalEntryRecord.model_validate(value))
    except (TypeError, ValueError):
        raise HTTPException(500, "Accounting storage contains an invalid journal entry.") from None


def _entry_statements(
    actor: dict[str, Any],
    *,
    entry_id: str,
    entry_date: str,
    financial_year: str,
    period_id: str,
    description: str,
    lines: list[dict[str, Any]],
    now: str,
    status: str = "Draft",
    source_type: str | None = None,
    source_id: str | None = None,
    reversal_of: str | None = None,
    correction_of: str | None = None,
    reason: str | None = None,
    authorization: str | None = None,
    audit_action: str | None = None,
) -> list[tuple[str, tuple[Any, ...]]]:
    insert_status = "Draft" if status == "Posted" else status
    statements: list[tuple[str, tuple[Any, ...]]] = [
        (
            """INSERT INTO journal_entries(
                   id, entry_date, financial_year, period_id, description, status,
                   source_type, source_id, reversal_of_entry_id, correction_of_entry_id,
                   created_by, created_at, posted_by, posted_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id, entry_date, financial_year, period_id, description, insert_status,
                source_type, source_id, reversal_of, correction_of,
                actor["id"], now, None, None,
            ),
        ),
    ]
    for line in lines:
        statements.append((
            """INSERT INTO journal_lines(
                   id, entry_id, line_no, account_id, description, debit_paise, credit_paise
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                _id("JL", f"{entry_id}:{line['lineNo']}"), entry_id, line["lineNo"], line["accountId"],
                line.get("description"), line["debitPaise"], line["creditPaise"],
            ),
        ))
    if status == "Posted":
        statements.append((
            "UPDATE journal_entries SET status = 'Posted', posted_by = ?, posted_at = ? WHERE id = ?",
            (actor["id"], now, entry_id),
        ))
    statements.append(_audit_statement(
        actor,
        action=audit_action or ("journal.entry.created" if status == "Draft" else "journal.entry.posted"),
        entity_type="journal_entry", entity_id=entry_id, now=now,
        financial_year=financial_year, period_id=period_id, reason=reason, authorization=authorization,
        details={"status": status, "lineCount": len(lines), "totalPaise": sum(x["debitPaise"] for x in lines), "sourceType": source_type},
    ))
    return statements


async def create_entry(store: D1Store, payload: JournalEntryCreate, user: dict[str, Any], now: str) -> dict[str, Any]:
    actor = await _actor(store, user)
    period, period_statements = await _period_for_entry(
        store, entry_date=payload.date, financial_year=payload.financialYear,
        period_id=payload.periodId, actor=actor, now=now,
    )
    _assert_open(period)
    lines, _ = await _validate_lines(store, payload.lines)
    if payload.reversalOfEntryId or payload.correctionOfEntryId:
        linked_id = payload.reversalOfEntryId or payload.correctionOfEntryId
        linked = await store.first("SELECT id, status FROM journal_entries WHERE id = ?", linked_id)
        if linked is None or linked["status"] != "Posted":
            raise HTTPException(422, "A reversal or correction must link to an existing posted journal entry.")
    entry_id = payload.id or _id("JE")
    statements = period_statements + _entry_statements(
        actor, entry_id=entry_id, entry_date=payload.date, financial_year=payload.financialYear,
        period_id=period["id"], description=payload.description, lines=lines, now=now,
        source_type=payload.sourceType, source_id=payload.sourceId,
        reversal_of=payload.reversalOfEntryId, correction_of=payload.correctionOfEntryId,
    )
    await _commit(store, statements)
    return await _entry_record(store, entry_id)


async def post_entry(store: D1Store, entry_id: str, payload: JournalPostRequest, user: dict[str, Any], now: str) -> dict[str, Any]:
    actor = await _actor(store, user)
    row = await store.first("SELECT * FROM journal_entries WHERE id = ?", entry_id)
    if row is None:
        raise HTTPException(404, "The journal entry was not found.")
    if row["status"] != "Draft":
        raise HTTPException(409, "Only a draft journal entry can be posted.")
    period = await store.first("SELECT * FROM accounting_periods WHERE id = ?", row["period_id"])
    if period is None:
        raise HTTPException(422, "The journal entry references an unknown accounting period.")
    _assert_open(period)
    raw_lines = [
        {"accountId": line["account_id"], "debitPaise": line["debit_paise"], "creditPaise": line["credit_paise"], "description": line.get("description")}
        for line in await store.all("SELECT * FROM journal_lines WHERE entry_id = ? ORDER BY line_no", entry_id)
    ]
    lines, _ = await _validate_lines(store, raw_lines)
    statements = [
        ("UPDATE journal_entries SET status = 'Posted', posted_by = ?, posted_at = ? WHERE id = ?", (actor["id"], now, entry_id)),
        _audit_statement(
            actor, action="journal.entry.posted", entity_type="journal_entry", entity_id=entry_id, now=now,
            financial_year=row["financial_year"], period_id=row["period_id"], reason=payload.reason,
            details={"status": "Posted", "lineCount": len(lines), "totalPaise": sum(x["debitPaise"] for x in lines)},
        ),
    ]
    await _commit(store, statements)
    return await _entry_record(store, entry_id)


async def reverse_entry(store: D1Store, entry_id: str, payload: JournalReversalRequest, user: dict[str, Any], now: str) -> dict[str, Any]:
    actor = await _actor(store, user)
    source = await store.first("SELECT * FROM journal_entries WHERE id = ?", entry_id)
    if source is None:
        raise HTTPException(404, "The journal entry was not found.")
    if source["status"] != "Posted":
        raise HTTPException(409, "Only a posted journal entry can be reversed.")
    if source.get("reversal_of_entry_id") or source.get("correction_of_entry_id"):
        raise HTTPException(409, "A reversal or correction entry cannot be reversed through this endpoint.")
    existing = await store.first("SELECT id FROM journal_entries WHERE reversal_of_entry_id = ?", entry_id)
    if existing is not None:
        raise HTTPException(409, "This journal entry already has a reversal.")
    entry_date = payload.date or source["entry_date"]
    financial_year = financial_year_for_date(date.fromisoformat(entry_date))
    period, period_statements = await _period_for_entry(
        store, entry_date=entry_date, financial_year=financial_year,
        period_id=payload.periodId or (source["period_id"] if entry_date == source["entry_date"] else None), actor=actor, now=now,
    )
    _assert_open(period)
    source_lines = await store.all("SELECT * FROM journal_lines WHERE entry_id = ? ORDER BY line_no", entry_id)
    raw_lines = [
        {"accountId": line["account_id"], "debitPaise": line["credit_paise"], "creditPaise": line["debit_paise"], "description": f"Reversal of {entry_id}"}
        for line in source_lines
    ]
    lines, _ = await _validate_lines(store, raw_lines)
    reversal_id = _id("JE-REV", entry_id)
    statements = period_statements + _entry_statements(
        actor, entry_id=reversal_id, entry_date=entry_date, financial_year=financial_year,
        period_id=period["id"], description=payload.description or f"Reversal of {entry_id}: {payload.reason}",
        lines=lines, now=now, status="Posted", source_type="reversal", source_id=entry_id,
        reversal_of=entry_id, reason=payload.reason, authorization=payload.authorization, audit_action="journal.entry.reversed",
    )
    await _commit(store, statements)
    return await _entry_record(store, reversal_id)


async def correct_entry(store: D1Store, entry_id: str, payload: JournalCorrectionRequest, user: dict[str, Any], now: str) -> dict[str, Any]:
    actor = await _actor(store, user)
    source = await store.first("SELECT * FROM journal_entries WHERE id = ?", entry_id)
    if source is None:
        raise HTTPException(404, "The journal entry was not found.")
    if source["status"] != "Posted":
        raise HTTPException(409, "Only a posted journal entry can be corrected.")
    entry_date = payload.date or source["entry_date"]
    financial_year = payload.financialYear or financial_year_for_date(date.fromisoformat(entry_date))
    period, period_statements = await _period_for_entry(
        store, entry_date=entry_date, financial_year=financial_year,
        period_id=payload.periodId or (source["period_id"] if entry_date == source["entry_date"] else None), actor=actor, now=now,
    )
    _assert_open(period)
    lines, _ = await _validate_lines(store, payload.lines)
    correction_id = _id("JE-COR", entry_id)
    statements = period_statements + _entry_statements(
        actor, entry_id=correction_id, entry_date=entry_date, financial_year=financial_year,
        period_id=period["id"], description=payload.description or f"Correction of {entry_id}: {payload.reason}",
        lines=lines, now=now, status="Posted", source_type="correction", source_id=entry_id,
        correction_of=entry_id, reason=payload.reason, authorization=payload.authorization, audit_action="journal.entry.corrected",
    )
    await _commit(store, statements)
    return await _entry_record(store, correction_id)


async def list_entries(store: D1Store) -> list[dict[str, Any]]:
    rows = await store.all("SELECT id FROM journal_entries ORDER BY entry_date DESC, created_at DESC, id")
    return [await _entry_record(store, row["id"]) for row in rows]


async def close_period(store: D1Store, period_id: str, payload: PeriodActionRequest, user: dict[str, Any], now: str) -> dict[str, Any]:
    actor = await _actor(store, user)
    period = await store.first("SELECT * FROM accounting_periods WHERE id = ?", period_id)
    if period is None:
        raise HTTPException(404, "The accounting period was not found.")
    if period["status"] == "Closed":
        raise HTTPException(409, "The accounting period is already closed.")
    draft = await store.first("SELECT COUNT(*) AS count FROM journal_entries WHERE period_id = ? AND status = 'Draft'", period_id)
    if draft and int(draft["count"]) > 0:
        raise HTTPException(409, "Post or remove all draft journal entries before closing the period.")
    integrity = await store.all(
        """SELECT e.id, COUNT(l.id) AS line_count,
                  COALESCE(SUM(l.debit_paise), 0) AS debit_total,
                  COALESCE(SUM(l.credit_paise), 0) AS credit_total
           FROM journal_entries e LEFT JOIN journal_lines l ON l.entry_id = e.id
           WHERE e.period_id = ? GROUP BY e.id""",
        period_id,
    )
    if any(int(row["line_count"]) < 2 or int(row["debit_total"]) != int(row["credit_total"]) for row in integrity):
        raise HTTPException(409, "The accounting period contains an unbalanced journal entry.")
    statements = [
        (
            """UPDATE accounting_periods
               SET status = 'Closed', closed_at = ?, closed_by = ?, close_reason = ?, close_authorization = ?
               WHERE id = ?""",
            (now, actor["id"], payload.reason, payload.authorization, period_id),
        ),
        _audit_statement(
            actor, action="period.closed", entity_type="accounting_period", entity_id=period_id, now=now,
            financial_year=period["financial_year"], period_id=period_id, reason=payload.reason,
            authorization=payload.authorization, details={"status": "Closed"},
        ),
    ]
    await _commit(store, statements)
    row = await store.first("SELECT * FROM accounting_periods WHERE id = ?", period_id)
    if row is None:
        raise D1Error("The closed accounting period could not be read.")
    return _period(row)


async def reopen_period(store: D1Store, period_id: str, payload: PeriodActionRequest, user: dict[str, Any], now: str) -> dict[str, Any]:
    actor = await _actor(store, user)
    period = await store.first("SELECT * FROM accounting_periods WHERE id = ?", period_id)
    if period is None:
        raise HTTPException(404, "The accounting period was not found.")
    if period["status"] != "Closed":
        raise HTTPException(409, "The accounting period is already open.")
    statements = [
        (
            """UPDATE accounting_periods
               SET status = 'Open', reopened_at = ?, reopened_by = ?, reopen_reason = ?, reopen_authorization = ?
               WHERE id = ?""",
            (now, actor["id"], payload.reason, payload.authorization, period_id),
        ),
        _audit_statement(
            actor, action="period.reopened", entity_type="accounting_period", entity_id=period_id, now=now,
            financial_year=period["financial_year"], period_id=period_id, reason=payload.reason,
            authorization=payload.authorization, details={"status": "Open"},
        ),
    ]
    await _commit(store, statements)
    row = await store.first("SELECT * FROM accounting_periods WHERE id = ?", period_id)
    if row is None:
        raise D1Error("The reopened accounting period could not be read.")
    return _period(row)


async def list_audit_events(
    store: D1Store,
    *,
    period_id: str | None = None,
    entity_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    clauses: list[str] = []
    parameters: list[Any] = []
    if period_id:
        clauses.append("period_id = ?")
        parameters.append(period_id)
    if entity_type:
        clauses.append("entity_type = ?")
        parameters.append(entity_type)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    parameters.append(limit)
    rows = await store.all(f"SELECT * FROM audit_events{where} ORDER BY occurred_at DESC, id DESC LIMIT ?", *parameters)
    return [_audit(row) for row in rows]
