"""Normalized double-entry accounting foundation for the local API.

The operational portal ledger and imported Tally snapshot remain separate. This
module owns only the new chart-of-accounts, journal, period, and append-only
audit tables. No historical row is converted into a journal automatically.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import date
from typing import Any, Iterable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from .portal import _body, committee_user
from .portal_models import (
    AccountCreate,
    AccountingPeriodCreate,
    JournalCorrectionRequest,
    JournalEntryCreate,
    JournalEntryRecord,
    JournalLineInput,
    JournalPostRequest,
    JournalReversalRequest,
    PeriodActionRequest,
    financial_year_for_date,
    json_record,
)


router = APIRouter()

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

ACCOUNTING_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('Asset', 'Liability', 'Equity', 'Income', 'Expense')),
    parent_id TEXT REFERENCES accounts(id),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_accounts_parent ON accounts(parent_id);
CREATE INDEX IF NOT EXISTS idx_accounts_active ON accounts(active);

CREATE TABLE IF NOT EXISTS accounting_periods (
    id TEXT PRIMARY KEY,
    financial_year TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open', 'Closed')),
    closed_at TEXT,
    closed_by TEXT REFERENCES users(id),
    close_reason TEXT,
    close_authorization TEXT,
    reopened_at TEXT,
    reopened_by TEXT REFERENCES users(id),
    reopen_reason TEXT,
    reopen_authorization TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(financial_year, start_date, end_date),
    CHECK (start_date < end_date)
);
CREATE INDEX IF NOT EXISTS idx_accounting_periods_year ON accounting_periods(financial_year);
CREATE INDEX IF NOT EXISTS idx_accounting_periods_status ON accounting_periods(status);

CREATE TABLE IF NOT EXISTS journal_entries (
    id TEXT PRIMARY KEY,
    entry_date TEXT NOT NULL,
    financial_year TEXT NOT NULL,
    period_id TEXT NOT NULL REFERENCES accounting_periods(id),
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft', 'Posted')),
    source_type TEXT,
    source_id TEXT,
    reversal_of_entry_id TEXT REFERENCES journal_entries(id),
    correction_of_entry_id TEXT REFERENCES journal_entries(id),
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    posted_by TEXT REFERENCES users(id),
    posted_at TEXT,
    CHECK (reversal_of_entry_id IS NULL OR correction_of_entry_id IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_journal_entries_period ON journal_entries(period_id, entry_date);
CREATE INDEX IF NOT EXISTS idx_journal_entries_status ON journal_entries(status);
CREATE INDEX IF NOT EXISTS idx_journal_entries_source ON journal_entries(source_type, source_id);

CREATE TABLE IF NOT EXISTS journal_lines (
    id TEXT PRIMARY KEY,
    entry_id TEXT NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    line_no INTEGER NOT NULL CHECK (line_no > 0),
    account_id TEXT NOT NULL REFERENCES accounts(id),
    description TEXT,
    debit_paise INTEGER NOT NULL DEFAULT 0 CHECK (typeof(debit_paise) = 'integer' AND debit_paise >= 0),
    credit_paise INTEGER NOT NULL DEFAULT 0 CHECK (typeof(credit_paise) = 'integer' AND credit_paise >= 0),
    CHECK ((debit_paise > 0 AND credit_paise = 0) OR (credit_paise > 0 AND debit_paise = 0)),
    UNIQUE(entry_id, line_no)
);
CREATE INDEX IF NOT EXISTS idx_journal_lines_entry ON journal_lines(entry_id, line_no);
CREATE INDEX IF NOT EXISTS idx_journal_lines_account ON journal_lines(account_id);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    actor_user_id TEXT NOT NULL REFERENCES users(id),
    actor_username TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    financial_year TEXT,
    period_id TEXT REFERENCES accounting_periods(id),
    reason TEXT,
    authorization TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_events_occurred ON audit_events(occurred_at, id);
CREATE INDEX IF NOT EXISTS idx_audit_events_entity ON audit_events(entity_type, entity_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_period ON audit_events(period_id, occurred_at);

CREATE TRIGGER IF NOT EXISTS journal_entries_posted_immutable
BEFORE UPDATE ON journal_entries
WHEN OLD.status = 'Posted'
BEGIN
    SELECT RAISE(ABORT, 'posted journal entry is immutable');
END;
CREATE TRIGGER IF NOT EXISTS journal_entries_posted_delete_forbidden
BEFORE DELETE ON journal_entries
WHEN OLD.status = 'Posted'
BEGIN
    SELECT RAISE(ABORT, 'posted journal entry is immutable');
END;
CREATE TRIGGER IF NOT EXISTS journal_lines_posted_immutable
BEFORE UPDATE ON journal_lines
WHEN EXISTS (SELECT 1 FROM journal_entries WHERE id = OLD.entry_id AND status = 'Posted')
BEGIN
    SELECT RAISE(ABORT, 'posted journal entry lines are immutable');
END;
CREATE TRIGGER IF NOT EXISTS journal_lines_posted_insert_forbidden
BEFORE INSERT ON journal_lines
WHEN EXISTS (SELECT 1 FROM journal_entries WHERE id = NEW.entry_id AND status = 'Posted')
BEGIN
    SELECT RAISE(ABORT, 'posted journal entry lines are immutable');
END;
CREATE TRIGGER IF NOT EXISTS journal_lines_posted_delete_forbidden
BEFORE DELETE ON journal_lines
WHEN EXISTS (SELECT 1 FROM journal_entries WHERE id = OLD.entry_id AND status = 'Posted')
BEGIN
    SELECT RAISE(ABORT, 'posted journal entry lines are immutable');
END;
CREATE TRIGGER IF NOT EXISTS journal_entry_closed_period_forbidden
BEFORE INSERT ON journal_entries
WHEN EXISTS (SELECT 1 FROM accounting_periods WHERE id = NEW.period_id AND status = 'Closed')
BEGIN
    SELECT RAISE(ABORT, 'accounting period is closed');
END;
CREATE TRIGGER IF NOT EXISTS journal_entry_post_closed_period_forbidden
BEFORE UPDATE OF status ON journal_entries
WHEN NEW.status = 'Posted' AND EXISTS (SELECT 1 FROM accounting_periods WHERE id = NEW.period_id AND status = 'Closed')
BEGIN
    SELECT RAISE(ABORT, 'accounting period is closed');
END;
CREATE TRIGGER IF NOT EXISTS audit_events_append_only_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit events are append-only');
END;
CREATE TRIGGER IF NOT EXISTS audit_events_append_only_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit events are append-only');
END;
"""


def _auth() -> Any:
    from . import auth

    return auth


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _id(prefix: str, source: str | None = None) -> str:
    if source:
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]
        return f"{prefix}-{digest}-{secrets.token_hex(6)}"
    return f"{prefix}-{secrets.token_hex(12)}"


def _now() -> str:
    return _auth().utc_now().isoformat()


def _db_error(error: sqlite3.IntegrityError) -> HTTPException:
    text = str(error).casefold()
    if "unique" in text:
        return HTTPException(409, "The accounting identity already exists.")
    if "closed" in text:
        return HTTPException(409, "The accounting period is closed.")
    if "immutable" in text:
        return HTTPException(409, "Posted journal entries are immutable; use a reversal or correction.")
    if "foreign key" in text:
        return HTTPException(422, "The accounting record references an unknown entity.")
    return HTTPException(422, "The accounting record violates a storage constraint.")


def initialize_accounting() -> None:
    """Create the normalized accounting schema and a minimal chart of accounts."""
    with _auth().database() as connection:
        connection.executescript(ACCOUNTING_SCHEMA)
        now = _now()
        for account_id, code, name, account_type in DEFAULT_ACCOUNTS:
            connection.execute(
                """INSERT OR IGNORE INTO accounts(id, code, name, account_type, parent_id, active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, NULL, 1, ?, ?)""",
                (account_id, code, name, account_type, now, now),
            )


def _actor(connection: sqlite3.Connection, user: dict[str, Any]) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM users WHERE id = ? AND active = 1", (user["id"],)).fetchone()
    if row is None or row["role"] != "committee":
        raise HTTPException(403, "Committee access is required.")
    return row


def _account_record(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return json_record(
        AccountCreate.model_validate({
            "id": row["id"],
            "code": row["code"],
            "name": row["name"],
            "accountType": row["account_type"],
            "parentId": row.get("parent_id") if isinstance(row, dict) else row["parent_id"],
            "active": bool(row["active"]),
        })
    ) | {
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _period_record(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    value = {
        "id": row["id"],
        "financialYear": row["financial_year"],
        "startDate": row["start_date"],
        "endDate": row["end_date"],
        "status": row["status"],
        "closedAt": row["closed_at"],
        "closedBy": row["closed_by"],
        "closeReason": row["close_reason"],
        "closeAuthorization": row["close_authorization"],
        "reopenedAt": row["reopened_at"],
        "reopenedBy": row["reopened_by"],
        "reopenReason": row["reopen_reason"],
        "reopenAuthorization": row["reopen_authorization"],
        "createdAt": row["created_at"],
    }
    return value


def _audit_record(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    try:
        details = json.loads(row["details_json"])
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
        "financialYear": row["financial_year"],
        "periodId": row["period_id"],
        "reason": row["reason"],
        "authorization": row["authorization"],
        "details": details,
    }


def _write_audit(
    connection: sqlite3.Connection,
    actor: sqlite3.Row,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    financial_year: str | None = None,
    period_id: str | None = None,
    reason: str | None = None,
    authorization: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        """INSERT INTO audit_events(
               id, occurred_at, actor_user_id, actor_username, action, entity_type,
               entity_id, financial_year, period_id, reason, authorization, details_json
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            _id("AUD"), _now(), actor["id"], actor["username"], action, entity_type,
            entity_id, financial_year, period_id, reason, authorization, _json(details or {}),
        ),
    )


def list_accounts(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_account_record(row) for row in connection.execute("SELECT * FROM accounts ORDER BY code, id")]


def create_account(connection: sqlite3.Connection, payload: AccountCreate, user: dict[str, Any]) -> dict[str, Any]:
    actor = _actor(connection, user)
    account_id = payload.id or _id("COA")
    if payload.parentId == account_id:
        raise HTTPException(422, "An account cannot be its own parent.")
    if payload.parentId:
        parent = connection.execute("SELECT id, active FROM accounts WHERE id = ?", (payload.parentId,)).fetchone()
        if parent is None:
            raise HTTPException(422, "The parent account does not exist.")
        if not parent["active"]:
            raise HTTPException(422, "The parent account is inactive.")
    now = _now()
    try:
        connection.execute(
            """INSERT INTO accounts(id, code, name, account_type, parent_id, active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (account_id, payload.code, payload.name, payload.accountType, payload.parentId, int(payload.active), now, now),
        )
        _write_audit(
            connection, actor, action="account.created", entity_type="account", entity_id=account_id,
            details={"code": payload.code, "accountType": payload.accountType},
        )
    except sqlite3.IntegrityError as error:
        raise _db_error(error) from None
    return _account_record(connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone())


def _period_id(payload: AccountingPeriodCreate) -> str:
    if payload.id:
        return payload.id
    start_year = int(payload.financialYear[:4])
    return f"FY-{start_year}-{str(start_year + 1)[-2:]}"


def _period_for_entry(
    connection: sqlite3.Connection,
    *,
    entry_date: str,
    financial_year: str,
    period_id: str | None,
    actor: sqlite3.Row,
    auto_create: bool = True,
) -> sqlite3.Row:
    parsed = date.fromisoformat(entry_date)
    if financial_year_for_date(parsed) != financial_year:
        raise HTTPException(422, "The journal date and financial year do not match.")
    if period_id:
        row = connection.execute("SELECT * FROM accounting_periods WHERE id = ?", (period_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "The accounting period was not found.")
        if row["financial_year"] != financial_year or not row["start_date"] <= entry_date <= row["end_date"]:
            raise HTTPException(422, "The journal date is outside the selected accounting period.")
        return row
    row = connection.execute(
        "SELECT * FROM accounting_periods WHERE financial_year = ? ORDER BY start_date LIMIT 1",
        (financial_year,),
    ).fetchone()
    if row is not None:
        if not row["start_date"] <= entry_date <= row["end_date"]:
            raise HTTPException(422, "The journal date is outside the accounting period.")
        return row
    if not auto_create:
        raise HTTPException(404, "The accounting period was not found.")
    start_year = int(financial_year[:4])
    period = AccountingPeriodCreate(
        financialYear=financial_year,
        startDate=f"{start_year}-04-01",
        endDate=f"{start_year + 1}-03-31",
    )
    period_id_value = _period_id(period)
    now = _now()
    try:
        connection.execute(
            """INSERT INTO accounting_periods(
                   id, financial_year, start_date, end_date, status, created_at
               ) VALUES (?, ?, ?, ?, 'Open', ?)""",
            (period_id_value, period.financialYear, period.startDate, period.endDate, now),
        )
        _write_audit(
            connection, actor, action="period.created", entity_type="accounting_period", entity_id=period_id_value,
            financial_year=period.financialYear, period_id=period_id_value,
            details={"automatic": True, "reason": "Created for a journal entry."},
        )
    except sqlite3.IntegrityError as error:
        raise _db_error(error) from None
    return connection.execute("SELECT * FROM accounting_periods WHERE id = ?", (period_id_value,)).fetchone()


def _assert_open(period: sqlite3.Row) -> None:
    if period["status"] != "Open":
        raise HTTPException(409, "The accounting period is closed.")


def _validate_lines(connection: sqlite3.Connection, lines: Iterable[JournalLineInput | dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    normalized: list[dict[str, Any]] = []
    debit_total = 0
    credit_total = 0
    for index, line in enumerate(lines, start=1):
        value = line if isinstance(line, dict) else line.model_dump()
        account = connection.execute("SELECT id, code, name, active FROM accounts WHERE id = ?", (value["accountId"],)).fetchone()
        if account is None:
            raise HTTPException(422, f"Unknown chart-of-accounts ID: {value['accountId']}.")
        if not account["active"]:
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


def _entry_record(connection: sqlite3.Connection, entry_id: str) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "The journal entry was not found.")
    lines = [
        {
            "id": line["id"],
            "lineNo": line["line_no"],
            "accountId": line["account_id"],
            "accountCode": line["code"],
            "accountName": line["name"],
            "description": line["description"],
            "debitPaise": line["debit_paise"],
            "creditPaise": line["credit_paise"],
        }
        for line in connection.execute(
            """SELECT l.*, a.code, a.name FROM journal_lines l
               JOIN accounts a ON a.id = l.account_id
               WHERE l.entry_id = ? ORDER BY l.line_no""",
            (entry_id,),
        )
    ]
    value = {
        "id": row["id"],
        "date": row["entry_date"],
        "financialYear": row["financial_year"],
        "periodId": row["period_id"],
        "description": row["description"],
        "status": row["status"],
        "sourceType": row["source_type"],
        "sourceId": row["source_id"],
        "reversalOfEntryId": row["reversal_of_entry_id"],
        "correctionOfEntryId": row["correction_of_entry_id"],
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
        "postedBy": row["posted_by"],
        "postedAt": row["posted_at"],
        "lines": lines,
    }
    try:
        return json_record(JournalEntryRecord.model_validate(value))
    except (TypeError, ValueError):
        raise HTTPException(500, "Accounting storage contains an invalid journal entry.") from None


def _insert_entry(
    connection: sqlite3.Connection,
    *,
    entry_id: str,
    entry_date: str,
    financial_year: str,
    period_id: str,
    description: str,
    lines: list[dict[str, Any]],
    actor: sqlite3.Row,
    status: str = "Draft",
    source_type: str | None = None,
    source_id: str | None = None,
    reversal_of: str | None = None,
    correction_of: str | None = None,
    reason: str | None = None,
    authorization: str | None = None,
    audit_action: str | None = None,
) -> None:
    now = _now()
    insert_status = "Draft" if status == "Posted" else status
    try:
        connection.execute(
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
        )
        for line in lines:
            line_id = _id("JL", f"{entry_id}:{line['lineNo']}")
            connection.execute(
                """INSERT INTO journal_lines(
                       id, entry_id, line_no, account_id, description, debit_paise, credit_paise
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    line_id, entry_id, line["lineNo"], line["accountId"], line.get("description"),
                    line["debitPaise"], line["creditPaise"],
                ),
            )
        if status == "Posted":
            connection.execute(
                "UPDATE journal_entries SET status = 'Posted', posted_by = ?, posted_at = ? WHERE id = ?",
                (actor["id"], now, entry_id),
            )
        _write_audit(
            connection, actor,
            action=audit_action or ("journal.entry.created" if status == "Draft" else "journal.entry.posted"),
            entity_type="journal_entry", entity_id=entry_id,
            financial_year=financial_year, period_id=period_id,
            reason=reason, authorization=authorization,
            details={"status": status, "lineCount": len(lines), "totalPaise": sum(x["debitPaise"] for x in lines), "sourceType": source_type},
        )
    except sqlite3.IntegrityError as error:
        raise _db_error(error) from None


def create_period(connection: sqlite3.Connection, payload: AccountingPeriodCreate, user: dict[str, Any]) -> dict[str, Any]:
    actor = _actor(connection, user)
    period_id = _period_id(payload)
    existing = connection.execute("SELECT * FROM accounting_periods WHERE id = ?", (period_id,)).fetchone()
    if existing is not None:
        if (
            existing["financial_year"], existing["start_date"], existing["end_date"]
        ) != (payload.financialYear, payload.startDate, payload.endDate):
            raise HTTPException(409, "The accounting period ID conflicts with existing period data.")
        return _period_record(existing)
    now = _now()
    try:
        connection.execute(
            """INSERT INTO accounting_periods(id, financial_year, start_date, end_date, status, created_at)
               VALUES (?, ?, ?, ?, 'Open', ?)""",
            (period_id, payload.financialYear, payload.startDate, payload.endDate, now),
        )
        _write_audit(
            connection, actor, action="period.created", entity_type="accounting_period", entity_id=period_id,
            financial_year=payload.financialYear, period_id=period_id,
            details={"automatic": False},
        )
    except sqlite3.IntegrityError as error:
        raise _db_error(error) from None
    return _period_record(connection.execute("SELECT * FROM accounting_periods WHERE id = ?", (period_id,)).fetchone())


def list_periods(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_period_record(row) for row in connection.execute("SELECT * FROM accounting_periods ORDER BY start_date DESC, id")]


def create_entry(connection: sqlite3.Connection, payload: JournalEntryCreate, user: dict[str, Any]) -> dict[str, Any]:
    actor = _actor(connection, user)
    period = _period_for_entry(
        connection, entry_date=payload.date, financial_year=payload.financialYear,
        period_id=payload.periodId, actor=actor,
    )
    _assert_open(period)
    lines, _ = _validate_lines(connection, payload.lines)
    if payload.reversalOfEntryId or payload.correctionOfEntryId:
        linked_id = payload.reversalOfEntryId or payload.correctionOfEntryId
        linked = connection.execute("SELECT id, status FROM journal_entries WHERE id = ?", (linked_id,)).fetchone()
        if linked is None or linked["status"] != "Posted":
            raise HTTPException(422, "A reversal or correction must link to an existing posted journal entry.")
    entry_id = payload.id or _id("JE")
    _insert_entry(
        connection, entry_id=entry_id, entry_date=payload.date, financial_year=payload.financialYear,
        period_id=period["id"], description=payload.description, lines=lines, actor=actor,
        source_type=payload.sourceType, source_id=payload.sourceId,
        reversal_of=payload.reversalOfEntryId, correction_of=payload.correctionOfEntryId,
    )
    return _entry_record(connection, entry_id)


def post_entry(connection: sqlite3.Connection, entry_id: str, payload: JournalPostRequest, user: dict[str, Any]) -> dict[str, Any]:
    actor = _actor(connection, user)
    row = connection.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "The journal entry was not found.")
    if row["status"] != "Draft":
        raise HTTPException(409, "Only a draft journal entry can be posted.")
    period = connection.execute("SELECT * FROM accounting_periods WHERE id = ?", (row["period_id"],)).fetchone()
    if period is None:
        raise HTTPException(422, "The journal entry references an unknown accounting period.")
    _assert_open(period)
    raw_lines = [
        {
            "accountId": line["account_id"],
            "debitPaise": line["debit_paise"],
            "creditPaise": line["credit_paise"],
            "description": line["description"],
        }
        for line in connection.execute("SELECT * FROM journal_lines WHERE entry_id = ? ORDER BY line_no", (entry_id,))
    ]
    lines, _ = _validate_lines(connection, raw_lines)
    now = _now()
    try:
        connection.execute("UPDATE journal_entries SET status = 'Posted', posted_by = ?, posted_at = ? WHERE id = ?", (actor["id"], now, entry_id))
        _write_audit(
            connection, actor, action="journal.entry.posted", entity_type="journal_entry", entity_id=entry_id,
            financial_year=row["financial_year"], period_id=row["period_id"], reason=payload.reason,
            details={"status": "Posted", "lineCount": len(lines), "totalPaise": sum(x["debitPaise"] for x in lines)},
        )
    except sqlite3.IntegrityError as error:
        raise _db_error(error) from None
    return _entry_record(connection, entry_id)


def reverse_entry(connection: sqlite3.Connection, entry_id: str, payload: JournalReversalRequest, user: dict[str, Any]) -> dict[str, Any]:
    actor = _actor(connection, user)
    source = connection.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
    if source is None:
        raise HTTPException(404, "The journal entry was not found.")
    if source["status"] != "Posted":
        raise HTTPException(409, "Only a posted journal entry can be reversed.")
    if source["reversal_of_entry_id"] or source["correction_of_entry_id"]:
        raise HTTPException(409, "A reversal or correction entry cannot be reversed through this endpoint.")
    existing = connection.execute("SELECT id FROM journal_entries WHERE reversal_of_entry_id = ?", (entry_id,)).fetchone()
    if existing is not None:
        raise HTTPException(409, "This journal entry already has a reversal.")
    entry_date = payload.date or source["entry_date"]
    financial_year = financial_year_for_date(date.fromisoformat(entry_date))
    period = _period_for_entry(
        connection, entry_date=entry_date, financial_year=financial_year,
        period_id=payload.periodId or (source["period_id"] if entry_date == source["entry_date"] else None), actor=actor,
    )
    _assert_open(period)
    source_lines = connection.execute("SELECT * FROM journal_lines WHERE entry_id = ? ORDER BY line_no", (entry_id,)).fetchall()
    raw_lines = [
        {
            "accountId": line["account_id"],
            "debitPaise": line["credit_paise"],
            "creditPaise": line["debit_paise"],
            "description": f"Reversal of {entry_id}",
        }
        for line in source_lines
    ]
    lines, _ = _validate_lines(connection, raw_lines)
    reversal_id = _id("JE-REV", entry_id)
    _insert_entry(
        connection, entry_id=reversal_id, entry_date=entry_date, financial_year=financial_year,
        period_id=period["id"], description=payload.description or f"Reversal of {entry_id}: {payload.reason}",
        lines=lines, actor=actor, status="Posted", source_type="reversal", source_id=entry_id,
        reversal_of=entry_id, reason=payload.reason, authorization=payload.authorization, audit_action="journal.entry.reversed",
    )
    return _entry_record(connection, reversal_id)


def correct_entry(connection: sqlite3.Connection, entry_id: str, payload: JournalCorrectionRequest, user: dict[str, Any]) -> dict[str, Any]:
    actor = _actor(connection, user)
    source = connection.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
    if source is None:
        raise HTTPException(404, "The journal entry was not found.")
    if source["status"] != "Posted":
        raise HTTPException(409, "Only a posted journal entry can be corrected.")
    entry_date = payload.date or source["entry_date"]
    financial_year = payload.financialYear or financial_year_for_date(date.fromisoformat(entry_date))
    period = _period_for_entry(
        connection, entry_date=entry_date, financial_year=financial_year,
        period_id=payload.periodId or (source["period_id"] if entry_date == source["entry_date"] else None), actor=actor,
    )
    _assert_open(period)
    lines, _ = _validate_lines(connection, payload.lines)
    correction_id = _id("JE-COR", entry_id)
    _insert_entry(
        connection, entry_id=correction_id, entry_date=entry_date, financial_year=financial_year,
        period_id=period["id"], description=payload.description or f"Correction of {entry_id}: {payload.reason}",
        lines=lines, actor=actor, status="Posted", source_type="correction", source_id=entry_id,
        correction_of=entry_id, reason=payload.reason, authorization=payload.authorization, audit_action="journal.entry.corrected",
    )
    return _entry_record(connection, correction_id)


def list_entries(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute("SELECT id FROM journal_entries ORDER BY entry_date DESC, created_at DESC, id").fetchall()
    return [_entry_record(connection, row["id"]) for row in rows]


def close_period(connection: sqlite3.Connection, period_id: str, payload: PeriodActionRequest, user: dict[str, Any]) -> dict[str, Any]:
    actor = _actor(connection, user)
    period = connection.execute("SELECT * FROM accounting_periods WHERE id = ?", (period_id,)).fetchone()
    if period is None:
        raise HTTPException(404, "The accounting period was not found.")
    if period["status"] == "Closed":
        raise HTTPException(409, "The accounting period is already closed.")
    draft = connection.execute("SELECT COUNT(*) AS count FROM journal_entries WHERE period_id = ? AND status = 'Draft'", (period_id,)).fetchone()["count"]
    if draft:
        raise HTTPException(409, "Post or remove all draft journal entries before closing the period.")
    integrity = connection.execute(
        """SELECT e.id, COUNT(l.id) AS line_count,
                  COALESCE(SUM(l.debit_paise), 0) AS debit_total,
                  COALESCE(SUM(l.credit_paise), 0) AS credit_total
           FROM journal_entries e LEFT JOIN journal_lines l ON l.entry_id = e.id
           WHERE e.period_id = ? GROUP BY e.id""",
        (period_id,),
    ).fetchall()
    if any(row["line_count"] < 2 or row["debit_total"] != row["credit_total"] for row in integrity):
        raise HTTPException(409, "The accounting period contains an unbalanced journal entry.")
    now = _now()
    connection.execute(
        """UPDATE accounting_periods
           SET status = 'Closed', closed_at = ?, closed_by = ?, close_reason = ?, close_authorization = ?
           WHERE id = ?""",
        (now, actor["id"], payload.reason, payload.authorization, period_id),
    )
    _write_audit(
        connection, actor, action="period.closed", entity_type="accounting_period", entity_id=period_id,
        financial_year=period["financial_year"], period_id=period_id, reason=payload.reason,
        authorization=payload.authorization, details={"status": "Closed"},
    )
    return _period_record(connection.execute("SELECT * FROM accounting_periods WHERE id = ?", (period_id,)).fetchone())


def reopen_period(connection: sqlite3.Connection, period_id: str, payload: PeriodActionRequest, user: dict[str, Any]) -> dict[str, Any]:
    actor = _actor(connection, user)
    period = connection.execute("SELECT * FROM accounting_periods WHERE id = ?", (period_id,)).fetchone()
    if period is None:
        raise HTTPException(404, "The accounting period was not found.")
    if period["status"] != "Closed":
        raise HTTPException(409, "The accounting period is already open.")
    now = _now()
    connection.execute(
        """UPDATE accounting_periods
           SET status = 'Open', reopened_at = ?, reopened_by = ?, reopen_reason = ?, reopen_authorization = ?
           WHERE id = ?""",
        (now, actor["id"], payload.reason, payload.authorization, period_id),
    )
    _write_audit(
        connection, actor, action="period.reopened", entity_type="accounting_period", entity_id=period_id,
        financial_year=period["financial_year"], period_id=period_id, reason=payload.reason,
        authorization=payload.authorization, details={"status": "Open"},
    )
    return _period_record(connection.execute("SELECT * FROM accounting_periods WHERE id = ?", (period_id,)).fetchone())


def list_audit_events(
    connection: sqlite3.Connection,
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
    rows = connection.execute(
        f"SELECT * FROM audit_events{where} ORDER BY occurred_at DESC, id DESC LIMIT ?",
        parameters,
    ).fetchall()
    return [_audit_record(row) for row in rows]


def _transaction(operation: Any, *args: Any) -> Any:
    with _auth().database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        return operation(connection, *args)


def _accounts_list(_: dict[str, Any]) -> list[dict[str, Any]]:
    with _auth().database() as connection:
        return list_accounts(connection)


@router.get("/api/admin/accounting/accounts")
@router.get("/api/admin/accounting/chart-of-accounts")
def accounting_accounts(user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    return {"accounts": _accounts_list(user)}


@router.post("/api/admin/accounting/accounts")
@router.post("/api/admin/accounting/chart-of-accounts")
async def accounting_create_account(request: Request, response: Response, user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    payload = await _body(request, AccountCreate, limit=32 * 1024)
    try:
        result = await run_in_threadpool(_transaction, create_account, payload, user)
    except sqlite3.IntegrityError as error:
        raise _db_error(error) from None
    response.headers["Cache-Control"] = "no-store"
    return {"account": result}


@router.get("/api/admin/accounting/periods")
def accounting_periods(user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    with _auth().database() as connection:
        return {"periods": list_periods(connection)}


@router.post("/api/admin/accounting/periods")
async def accounting_create_period(request: Request, response: Response, user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    payload = await _body(request, AccountingPeriodCreate, limit=16 * 1024)
    result = await run_in_threadpool(_transaction, create_period, payload, user)
    response.headers["Cache-Control"] = "no-store"
    return {"period": result}


@router.get("/api/admin/accounting/journal-entries")
@router.get("/api/admin/accounting/entries")
def accounting_entries(user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    with _auth().database() as connection:
        return {"entries": list_entries(connection)}


@router.get("/api/admin/accounting/journal-entries/{entry_id}")
@router.get("/api/admin/accounting/entries/{entry_id}")
def accounting_entry(entry_id: str, user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    with _auth().database() as connection:
        return {"entry": _entry_record(connection, entry_id)}


@router.post("/api/admin/accounting/journal-entries")
@router.post("/api/admin/accounting/entries")
async def accounting_create_entry(request: Request, response: Response, user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    payload = await _body(request, JournalEntryCreate, limit=256 * 1024)
    result = await run_in_threadpool(_transaction, create_entry, payload, user)
    response.headers["Cache-Control"] = "no-store"
    return {"entry": result}


@router.post("/api/admin/accounting/journal-entries/{entry_id}/post")
@router.post("/api/admin/accounting/entries/{entry_id}/post")
async def accounting_post_entry(entry_id: str, request: Request, response: Response, user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    payload = await _body(request, JournalPostRequest, limit=16 * 1024)
    result = await run_in_threadpool(_transaction, post_entry, entry_id, payload, user)
    response.headers["Cache-Control"] = "no-store"
    return {"entry": result}


@router.post("/api/admin/accounting/journal-entries/{entry_id}/reverse")
@router.post("/api/admin/accounting/entries/{entry_id}/reverse")
async def accounting_reverse_entry(entry_id: str, request: Request, response: Response, user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    payload = await _body(request, JournalReversalRequest, limit=32 * 1024)
    result = await run_in_threadpool(_transaction, reverse_entry, entry_id, payload, user)
    response.headers["Cache-Control"] = "no-store"
    return {"entry": result}


@router.post("/api/admin/accounting/journal-entries/{entry_id}/correct")
@router.post("/api/admin/accounting/entries/{entry_id}/correct")
async def accounting_correct_entry(entry_id: str, request: Request, response: Response, user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    payload = await _body(request, JournalCorrectionRequest, limit=256 * 1024)
    result = await run_in_threadpool(_transaction, correct_entry, entry_id, payload, user)
    response.headers["Cache-Control"] = "no-store"
    return {"entry": result}


@router.post("/api/admin/accounting/periods/{period_id}/close")
async def accounting_close_period(period_id: str, request: Request, response: Response, user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    payload = await _body(request, PeriodActionRequest, limit=16 * 1024)
    result = await run_in_threadpool(_transaction, close_period, period_id, payload, user)
    response.headers["Cache-Control"] = "no-store"
    return {"period": result}


@router.post("/api/admin/accounting/periods/{period_id}/reopen")
async def accounting_reopen_period(period_id: str, request: Request, response: Response, user: dict[str, Any] = Depends(committee_user)) -> dict[str, Any]:
    payload = await _body(request, PeriodActionRequest, limit=16 * 1024)
    result = await run_in_threadpool(_transaction, reopen_period, period_id, payload, user)
    response.headers["Cache-Control"] = "no-store"
    return {"period": result}


@router.get("/api/admin/accounting/audit-events")
@router.get("/api/admin/accounting/audit")
def accounting_audit(
    periodId: str | None = None,
    entityType: str | None = None,
    limit: int = 100,
    user: dict[str, Any] = Depends(committee_user),
) -> dict[str, Any]:
    with _auth().database() as connection:
        return {"events": list_audit_events(connection, period_id=periodId, entity_type=entityType, limit=limit)}
