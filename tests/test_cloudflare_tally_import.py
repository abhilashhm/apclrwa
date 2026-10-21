import copy
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException, Request, Response

import cloudflare.app as app_module
from cloudflare import domain
from cloudflare.d1 import D1Conflict, D1Store
from cloudflare.portal_models import MAX_PAYLOAD_BYTES, TallyImport


COMMITTEE = {
    "id": "USR-COMMITTEE",
    "username": "committee",
    "display_name": "Committee",
    "role": "committee",
    "active": 1,
    "resident_id": None,
    "must_change_password": 0,
}
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


class MemoryStore(D1Store):
    def __init__(self):
        super().__init__(object())
        self.revision = 0
        self.collections = domain.defaults()

    async def first(self, sql, *parameters):
        if "FROM users" in sql and parameters and parameters[0] == COMMITTEE["id"]:
            return copy.deepcopy(COMMITTEE)
        return None

    async def all(self, sql, *parameters):
        return []

    async def load_portal(self, defaults, now):
        return self.revision, copy.deepcopy(self.collections)

    async def save_portal(self, old, new, revision, now, *, force=False, extra_statements=()):
        if revision != self.revision:
            raise D1Conflict("portal revision conflict")
        if old != new or force:
            self.collections = copy.deepcopy(new)
            self.revision += 1
        return self.revision


def request_for(value, *, content_type="application/json", declared_length=None):
    body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    length = len(body) if declared_length is None else declared_length
    headers = [(b"content-type", content_type.encode("ascii")), (b"content-length", str(length).encode("ascii"))]
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/admin/tally-import/apply",
        "headers": headers,
        "query_string": b"",
        "scheme": "https",
        "server": ("test", 443),
        "client": ("127.0.0.1", 1234),
    }
    return Request(scope, receive)


def ledger_row(*, row_id="ADV-1", amount=1000.0, payment_id=None, status="Posted"):
    row = {
        "id": row_id,
        "kind": "Advance AMC",
        "amount": amount,
        "house": "A-1",
        "description": "AMC advance",
        "mode": "UPI",
        "date": "2026-02-01",
        "financialYear": "2025–26",
        "amcForFinancialYear": "2026–27",
        "status": status,
        "bucket": "AMC",
    }
    if payment_id is not None:
        row["paymentId"] = payment_id
    return row


def tally_snapshot(*, import_id="TALLY-1", transactions=None, opening=None):
    return TallyImport.model_validate({
        "importId": import_id,
        "financialYear": "2026–27",
        "sourceFiles": ["Bank.xls", "Cash.xls"],
        "openingBalances": opening or {
            "financialYear": "2026–27",
            "date": "2026-04-01",
            "bank": 100.0,
            "cash": 20.0,
        },
        "reconciliation": {
            "financialYear": "2026–27",
            "sourcePeriodThrough": "2026-09-30",
            "bank": {"opening": 100.0, "receipts": 50.0, "payments": 10.0, "closing": 140.0, "calculatedClosing": 140.0},
            "cash": {"opening": 20.0, "receipts": 10.0, "payments": 5.0, "closing": 25.0, "calculatedClosing": 25.0},
            "checks": [],
        },
        "transactions": transactions if transactions is not None else [ledger_row()],
    })


class CloudflareTallyImportTests(unittest.IsolatedAsyncioTestCase):
    async def call_route(self, store, value):
        async def committee(*args, **kwargs):
            return {"id": COMMITTEE["id"], "username": "committee", "role": "committee"}

        request = request_for(value)
        response = Response()
        with (
            patch.object(app_module, "store_for", return_value=store),
            patch.object(app_module, "require_committee", new=committee),
            patch.object(app_module, "utc_now", return_value=NOW),
        ):
            return await app_module.apply_tally_import(request, response), response

    async def test_valid_direct_snapshot_import_persists_ledger_opening_reconciliation_and_transfer(self):
        store = MemoryStore()
        snapshot = tally_snapshot()
        body = {"revision": 0, **snapshot.model_dump(mode="json", exclude_none=True)}

        result, response = await self.call_route(store, body)

        self.assertEqual(result["revision"], 1)
        self.assertEqual([row["id"] for row in result["collections"]["ledger"]], ["ADV-1", "AMC-XFER-ADV-1"])
        self.assertEqual(result["collections"]["openingBalances"]["bank"], 100.0)
        self.assertEqual(result["collections"]["tallyReconciliation"]["importId"], "TALLY-1")
        self.assertEqual(result["collections"]["tallyReconciliation"]["transactionCount"], 1)
        self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_repeating_identical_snapshot_is_idempotent_even_with_stale_revision(self):
        store = MemoryStore()
        snapshot = tally_snapshot()
        first, _ = await self.call_route(store, {"revision": 0, "snapshot": snapshot.model_dump(mode="json", exclude_none=True)})
        imported_at = first["collections"]["tallyReconciliation"]["importedAt"]

        repeated, _ = await self.call_route(store, {"revision": 0, "snapshot": snapshot.model_dump(mode="json", exclude_none=True)})

        self.assertEqual(repeated["revision"], 1)
        self.assertEqual(repeated["collections"]["ledger"], first["collections"]["ledger"])
        self.assertEqual(repeated["collections"]["tallyReconciliation"]["importedAt"], imported_at)

    async def test_new_snapshot_appends_new_stable_ids_and_stores_new_reconciliation(self):
        store = MemoryStore()
        first = tally_snapshot(import_id="TALLY-1")
        await self.call_route(store, {"revision": 0, "snapshot": first.model_dump(mode="json", exclude_none=True)})
        second = tally_snapshot(import_id="TALLY-2", transactions=[ledger_row(row_id="ADV-2", amount=1200.0)])

        result, _ = await self.call_route(store, {"revision": store.revision, "snapshot": second.model_dump(mode="json", exclude_none=True)})

        self.assertEqual(result["revision"], 2)
        self.assertEqual([row["id"] for row in result["collections"]["ledger"]], [
            "ADV-1", "AMC-XFER-ADV-1", "ADV-2", "AMC-XFER-ADV-2",
        ])
        self.assertEqual(result["collections"]["openingBalances"]["bank"], 100.0)
        self.assertEqual(result["collections"]["tallyReconciliation"]["importId"], "TALLY-2")

    async def test_payment_managed_rows_are_rejected(self):
        store = MemoryStore()
        snapshot = tally_snapshot(transactions=[ledger_row(payment_id="PAY-1")])

        with self.assertRaises(HTTPException) as raised:
            await self.call_route(store, {"revision": 0, "snapshot": snapshot.model_dump(mode="json", exclude_none=True)})

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(store.revision, 0)

    async def test_existing_ledger_identity_and_opening_balance_conflicts_are_rejected(self):
        store = MemoryStore()
        original = tally_snapshot()
        await self.call_route(store, {"revision": 0, "snapshot": original.model_dump(mode="json", exclude_none=True)})

        conflicting_ledger = tally_snapshot(import_id="TALLY-2", transactions=[ledger_row(amount=1100.0)])
        with self.assertRaises(HTTPException) as ledger_error:
            await self.call_route(store, {"revision": store.revision, "snapshot": conflicting_ledger.model_dump(mode="json", exclude_none=True)})
        self.assertEqual(ledger_error.exception.status_code, 409)

        conflicting_opening = tally_snapshot(
            import_id="TALLY-3",
            transactions=[ledger_row()],
            opening={"financialYear": "2026–27", "date": "2026-04-01", "bank": 101.0, "cash": 20.0},
        )
        with self.assertRaises(HTTPException) as opening_error:
            await self.call_route(store, {"revision": store.revision, "snapshot": conflicting_opening.model_dump(mode="json", exclude_none=True)})
        self.assertEqual(opening_error.exception.status_code, 409)

    async def test_invalid_json_model_and_non_committee_requests_are_sanitized(self):
        store = MemoryStore()
        invalid = request_for(b'{"revision":0,"snapshot":{"importId":"TALLY-1"}}')
        response = Response()
        async def committee(*args, **kwargs):
            return {"id": COMMITTEE["id"], "username": "committee", "role": "committee"}
        with patch.object(app_module, "store_for", return_value=store), patch.object(app_module, "require_committee", new=committee):
            with self.assertRaises(HTTPException) as raised:
                await app_module.apply_tally_import(invalid, response)
        self.assertEqual(raised.exception.status_code, 422)
        self.assertNotIn("validation", str(raised.exception.detail).casefold())

        malformed = request_for(b'{"revision":0,')
        with patch.object(app_module, "store_for", return_value=store), patch.object(app_module, "require_committee", new=committee):
            with self.assertRaises(HTTPException) as malformed_error:
                await app_module.apply_tally_import(malformed, Response())
        self.assertEqual(malformed_error.exception.status_code, 400)

        wrong_type = request_for({}, content_type="text/plain")
        with patch.object(app_module, "store_for", return_value=store), patch.object(app_module, "require_committee", new=committee):
            with self.assertRaises(HTTPException) as content_type_error:
                await app_module.apply_tally_import(wrong_type, Response())
        self.assertEqual(content_type_error.exception.status_code, 415)

        oversized = request_for({}, declared_length=MAX_PAYLOAD_BYTES + 1)
        with patch.object(app_module, "store_for", return_value=store), patch.object(app_module, "require_committee", new=committee):
            with self.assertRaises(HTTPException) as size_error:
                await app_module.apply_tally_import(oversized, Response())
        self.assertEqual(size_error.exception.status_code, 413)

        denied = request_for({})
        async def deny(*args, **kwargs):
            raise HTTPException(403, "Committee access is required.")
        with patch.object(app_module, "store_for", return_value=store), patch.object(app_module, "require_committee", new=deny):
            with self.assertRaises(HTTPException) as denied_error:
                await app_module.apply_tally_import(denied, Response())
        self.assertEqual(denied_error.exception.status_code, 403)

    async def test_local_style_revision_only_request_explains_that_cloud_upload_is_required(self):
        store = MemoryStore()
        async def committee(*args, **kwargs):
            return COMMITTEE
        with patch.object(app_module, "store_for", return_value=store), patch.object(app_module, "require_committee", new=committee):
            with self.assertRaises(HTTPException) as raised:
                await app_module.apply_tally_import(request_for({"revision": 0}), Response())
        self.assertEqual(raised.exception.status_code, 501)


if __name__ == "__main__":
    unittest.main()
