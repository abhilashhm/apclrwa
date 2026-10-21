import unittest
from datetime import date

from cloudflare import domain


class CloudflareDomainTests(unittest.TestCase):
    def test_resident_password_is_write_only(self):
        residents, passwords = domain.collection(
            "residents",
            [{
                "id": "RES-1",
                "house": "A-1",
                "name": "Resident One",
                "mobile": "+91 98765 43210",
                "password": "a-temporary-password",
            }],
        )
        self.assertEqual(passwords, {"RES-1": "a-temporary-password"})
        self.assertNotIn("password", residents[0])
        self.assertEqual(residents[0]["mobile"], "9876543210")

    def test_automatic_amc_transfer_is_deterministic(self):
        collections = domain.defaults()
        collections["ledger"] = [{
            "id": "ADV-1",
            "kind": "Advance AMC",
            "amount": 1000.0,
            "house": "A-1",
            "residentId": "RES-1",
            "description": "AMC advance",
            "mode": "UPI",
            "date": "2026-02-01",
            "financialYear": "2025–26",
            "amcForFinancialYear": "2026–27",
            "status": "Posted",
            "bucket": "AMC",
        }]
        domain.ensure_transfers(collections, date(2026, 4, 1))
        self.assertEqual(len(collections["ledger"]), 2)
        transfer = collections["ledger"][1]
        self.assertEqual(transfer["id"], "AMC-XFER-ADV-1")
        self.assertEqual(transfer["transferOf"], "ADV-1")
        self.assertEqual(transfer["date"], "2026-04-01")

    def test_membership_payment_posts_to_membership_ledger(self):
        receipt = domain.posted_receipt({
            "id": "PAY-1",
            "type": "Membership",
            "numericAmount": 500.0,
            "house": "A-1",
            "residentId": "RES-1",
            "details": "Membership fee",
            "mode": "UPI",
            "transactionDate": "2026-10-21",
            "financialYear": "2026–27",
            "createdAt": "2026-10-21T12:00:00+00:00",
        }, "2026-10-21T12:00:01+00:00")
        self.assertEqual(receipt["id"], "MEM-PAY-1")
        self.assertEqual(receipt["kind"], "Membership")
        self.assertEqual(receipt["residentId"], "RES-1")
        self.assertEqual(receipt["paymentId"], "PAY-1")
        self.assertEqual(receipt["status"], "Posted")

    def test_storage_limit_rejects_large_collection(self):
        collections = domain.defaults()
        collections["events"] = [{
            "id": f"E-{index}",
            "title": "Event",
            "text": "x" * 240,
            "location": "APC Layout",
        } for index in range(25001)]
        with self.assertRaises(ValueError):
            domain.validate_storage_limits(collections)


if __name__ == "__main__":
    unittest.main()
