import sqlite3
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from backend import accounting as local_accounting
from backend.portal_models import (
    AccountingPeriodCreate,
    JournalEntryCreate,
    JournalPostRequest,
    JournalReversalRequest,
    PeriodActionRequest,
)
from cloudflare import accounting as worker_accounting
from cloudflare.portal_models import JournalEntryCreate as WorkerJournalEntryCreate


COMMITTEE = {"id": "USR-COMMITTEE", "username": "committee"}
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def entry_payload(entry_id: str = "JE-1") -> JournalEntryCreate:
    return JournalEntryCreate.model_validate({
        "id": entry_id,
        "date": "2026-10-22",
        "financialYear": "2026–27",
        "description": "Bank receipt",
        "lines": [
            {"accountId": "COA-BANK", "debitPaise": 12500, "creditPaise": 0},
            {"accountId": "COA-MAINTENANCE", "debitPaise": 0, "creditPaise": 12500},
        ],
    })


class AccountingContractTests(unittest.TestCase):
    def test_entries_require_multiple_balanced_lines_and_matching_financial_year(self):
        with self.assertRaises(ValidationError):
            JournalEntryCreate.model_validate({
                "date": "2026-10-22",
                "financialYear": "2026–27",
                "description": "One line",
                "lines": [{"accountId": "COA-BANK", "debitPaise": 100, "creditPaise": 0}],
            })
        with self.assertRaises(ValidationError):
            JournalEntryCreate.model_validate({
                "date": "2026-10-22",
                "financialYear": "2026–27",
                "description": "Unbalanced",
                "lines": [
                    {"accountId": "COA-BANK", "debitPaise": 100, "creditPaise": 0},
                    {"accountId": "COA-MAINTENANCE", "debitPaise": 0, "creditPaise": 99},
                ],
            })
        with self.assertRaises(ValidationError):
            JournalEntryCreate.model_validate({
                "date": "2026-10-22",
                "financialYear": "2025–26",
                "description": "Wrong FY",
                "lines": [
                    {"accountId": "COA-BANK", "debitPaise": 100, "creditPaise": 0},
                    {"accountId": "COA-MAINTENANCE", "debitPaise": 0, "creditPaise": 100},
                ],
            })

    def test_period_contract_covers_april_to_march(self):
        with self.assertRaises(ValidationError):
            AccountingPeriodCreate.model_validate({
                "financialYear": "2026–27",
                "startDate": "2026-04-02",
                "endDate": "2027-03-31",
            })


class LocalAccountingTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute(
            "CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT, role TEXT, active INTEGER)"
        )
        self.connection.execute("INSERT INTO users VALUES ('USR-COMMITTEE', 'committee', 'committee', 1)")
        self.connection.executescript(local_accounting.ACCOUNTING_SCHEMA)
        for account_id, code, name, account_type in local_accounting.DEFAULT_ACCOUNTS:
            self.connection.execute(
                "INSERT INTO accounts(id, code, name, account_type, active, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
                (account_id, code, name, account_type, NOW.isoformat(), NOW.isoformat()),
            )
        self.connection.commit()

    def tearDown(self):
        self.connection.close()

    def run_in_transaction(self, function, *args):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            result = function(self.connection, *args)
        except Exception:
            self.connection.rollback()
            raise
        self.connection.commit()
        return result

    def test_posted_entries_are_immutable_and_reversal_is_a_new_linked_entry(self):
        with patch.object(local_accounting, "_now", return_value=NOW.isoformat()):
            draft = self.run_in_transaction(local_accounting.create_entry, entry_payload(), COMMITTEE)
            self.assertEqual(draft["status"], "Draft")
            posted = self.run_in_transaction(local_accounting.post_entry, "JE-1", JournalPostRequest(), COMMITTEE)
            self.assertEqual(posted["status"], "Posted")
            with self.assertRaises(sqlite3.IntegrityError):
                self.connection.execute("UPDATE journal_entries SET description = 'tampered' WHERE id = 'JE-1'")
            self.connection.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                self.connection.execute(
                    "INSERT INTO journal_lines(id, entry_id, line_no, account_id, debit_paise, credit_paise) VALUES ('JL-TAMPER', 'JE-1', 3, 'COA-CASH', 1, 0)"
                )
            self.connection.rollback()
            reversal = self.run_in_transaction(
                local_accounting.reverse_entry,
                "JE-1",
                JournalReversalRequest(reason="Correcting the receipt", authorization="MINUTES-12"),
                COMMITTEE,
            )
        self.assertEqual(reversal["status"], "Posted")
        self.assertEqual(reversal["reversalOfEntryId"], "JE-1")
        self.assertEqual(reversal["lines"][0]["debitPaise"], 0)
        actions = [row["action"] for row in self.connection.execute("SELECT action FROM audit_events ORDER BY occurred_at, id")]
        self.assertIn("journal.entry.created", actions)
        self.assertIn("journal.entry.posted", actions)
        self.assertIn("journal.entry.reversed", actions)

    def test_closed_period_rejects_entries_and_requires_authorized_reopen(self):
        with patch.object(local_accounting, "_now", return_value=NOW.isoformat()):
            self.run_in_transaction(local_accounting.create_entry, entry_payload(), COMMITTEE)
            self.run_in_transaction(local_accounting.post_entry, "JE-1", JournalPostRequest(), COMMITTEE)
            period_id = local_accounting.list_periods(self.connection)[0]["id"]
            closed = self.run_in_transaction(
                local_accounting.close_period,
                period_id,
                PeriodActionRequest(reason="Year-end close", authorization="MINUTES-13"),
                COMMITTEE,
            )
            self.assertEqual(closed["status"], "Closed")
            with self.assertRaises(HTTPException) as rejected:
                self.run_in_transaction(local_accounting.create_entry, entry_payload("JE-2"), COMMITTEE)
            self.assertEqual(rejected.exception.status_code, 409)
            reopened = self.run_in_transaction(
                local_accounting.reopen_period,
                period_id,
                PeriodActionRequest(reason="Approved adjustment", authorization="MINUTES-14"),
                COMMITTEE,
            )
        self.assertEqual(reopened["status"], "Open")
        self.assertEqual(reopened["reopenAuthorization"], "MINUTES-14")
        event = self.connection.execute(
            "SELECT reason, authorization FROM audit_events WHERE action = 'period.reopened'"
        ).fetchone()
        self.assertEqual((event["reason"], event["authorization"]), ("Approved adjustment", "MINUTES-14"))


class WorkerAccountingStatementTests(unittest.IsolatedAsyncioTestCase):
    async def test_d1_create_entry_batches_period_journal_lines_and_audit(self):
        class FakeStore(worker_accounting.D1Store):
            def __init__(self):
                super().__init__(object())
                self.batched = []

            async def first(self, sql, *parameters):
                if "FROM users" in sql:
                    return {"id": "USR-COMMITTEE", "username": "committee", "role": "committee", "active": 1}
                if "FROM accounting_periods" in sql:
                    return {
                        "id": "FY-2026-27", "financial_year": "2026–27", "start_date": "2026-04-01",
                        "end_date": "2027-03-31", "status": "Open", "created_at": NOW.isoformat(),
                    }
                if "FROM accounts" in sql:
                    account_id = parameters[0]
                    return {"id": account_id, "code": account_id, "name": account_id, "active": 1}
                if "FROM journal_entries" in sql:
                    return {
                        "id": "JE-CLOUD", "entry_date": "2026-10-22", "financial_year": "2026–27",
                        "period_id": "FY-2026-27", "description": "Cloud entry", "status": "Draft",
                        "created_by": "USR-COMMITTEE", "created_at": NOW.isoformat(),
                    }
                return None

            async def all(self, sql, *parameters):
                if "FROM journal_lines" in sql:
                    return [
                        {"id": "JL-1", "line_no": 1, "account_id": "COA-BANK", "code": "COA-BANK", "name": "COA-BANK", "description": None, "debit_paise": 12500, "credit_paise": 0},
                        {"id": "JL-2", "line_no": 2, "account_id": "COA-MAINTENANCE", "code": "COA-MAINTENANCE", "name": "COA-MAINTENANCE", "description": None, "debit_paise": 0, "credit_paise": 12500},
                    ]
                return []

            async def batch(self, statements):
                self.batched = list(statements)

        store = FakeStore()
        payload = WorkerJournalEntryCreate.model_validate({
            "id": "JE-CLOUD",
            "date": "2026-10-22",
            "financialYear": "2026–27",
            "periodId": "FY-2026-27",
            "description": "Cloud entry",
            "lines": [
                {"accountId": "COA-BANK", "debitPaise": 12500, "creditPaise": 0},
                {"accountId": "COA-MAINTENANCE", "debitPaise": 0, "creditPaise": 12500},
            ],
        })
        result = await worker_accounting.create_entry(store, payload, COMMITTEE, NOW.isoformat())
        self.assertEqual(result["id"], "JE-CLOUD")
        sql = "\n".join(statement for statement, _ in store.batched)
        self.assertIn("INSERT INTO journal_entries", sql)
        self.assertIn("INSERT INTO journal_lines", sql)
        self.assertIn("INSERT INTO audit_events", sql)


if __name__ == "__main__":
    unittest.main()
