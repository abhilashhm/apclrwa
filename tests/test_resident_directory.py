import copy
import sqlite3
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from pydantic import ValidationError

from backend import portal as backend_portal
from backend.portal_models import ResidentRecord as BackendResident
from backend.portal_models import json_record as backend_json_record
from cloudflare import app as cloudflare_app
from cloudflare import domain
from cloudflare.portal_models import ResidentRecord as CloudflareResident
from cloudflare.portal_models import json_record as cloudflare_json_record


BASE_RESIDENT = {
    "id": "RES-1",
    "house": "A-1",
    "name": "Resident One",
    "mobile": "9876543210",
    "residentType": "Tenant",
}


def resident_row(**changes):
    row = {**BASE_RESIDENT}
    row.update(changes)
    return row


class ResidentDirectoryModelTests(unittest.TestCase):
    def test_existing_rows_get_safe_defaults_and_blank_optional_fields_are_omitted(self):
        for model, json_dump in (
            (BackendResident, backend_json_record),
            (CloudflareResident, cloudflare_json_record),
        ):
            parsed = model.model_validate(resident_row())
            self.assertIsNone(parsed.profession)
            self.assertIsNone(parsed.tenantOwnerName)
            self.assertFalse(parsed.publicProfessionalListing)
            serialized = json_dump(model.model_validate(resident_row(profession="  ", tenantOwnerName="\t")))
            self.assertNotIn("profession", serialized)
            self.assertNotIn("tenantOwnerName", serialized)
            self.assertFalse(serialized["publicProfessionalListing"])

    def test_profession_and_tenant_owner_are_strict_and_consent_requires_listing_data(self):
        for model in (BackendResident, CloudflareResident):
            with self.assertRaises(ValidationError):
                model.model_validate(resident_row(profession=123))
            with self.assertRaises(ValidationError):
                model.model_validate(resident_row(publicProfessionalListing="true"))
            with self.assertRaises(ValidationError):
                model.model_validate(resident_row(profession="x" * 241))
            with self.assertRaises(ValidationError):
                model.model_validate(resident_row(publicProfessionalListing=True))

            parsed = model.model_validate(
                resident_row(
                    profession="  Architect ",
                    tenantOwnerName="  Property Owner ",
                    publicProfessionalListing=True,
                )
            )
            self.assertEqual(parsed.profession, "Architect")
            self.assertEqual(parsed.tenantOwnerName, "Property Owner")

    def test_new_fields_round_trip_without_password_leakage(self):
        value = resident_row(
            profession="Doctor",
            tenantOwnerName="Property Owner",
            publicProfessionalListing=True,
            password="a-temporary-password",
        )
        local_rows, local_passwords = backend_portal._collection("residents", [value])
        self.assertEqual(local_passwords, {"RES-1": "a-temporary-password"})
        self.assertEqual(local_rows[0]["profession"], "Doctor")
        self.assertEqual(local_rows[0]["tenantOwnerName"], "Property Owner")
        self.assertTrue(local_rows[0]["publicProfessionalListing"])
        self.assertNotIn("password", local_rows[0])

        worker_rows, worker_passwords = domain.collection("residents", [value])
        self.assertEqual(worker_passwords, {"RES-1": "a-temporary-password"})
        self.assertEqual(worker_rows, local_rows)

    def test_resident_snapshot_hides_private_fields_but_admin_can_manage_them(self):
        private_row = resident_row(
            profession="Doctor",
            tenantOwnerName="Property Owner",
            publicProfessionalListing=False,
        )
        opted_in_row = {**private_row, "publicProfessionalListing": True}

        local_resident = backend_portal._public_resident(private_row, None)
        self.assertNotIn("profession", local_resident)
        self.assertNotIn("tenantOwnerName", local_resident)
        self.assertNotIn("publicProfessionalListing", local_resident)
        local_admin = backend_portal._public_resident(private_row, None, include_private=True)
        self.assertEqual(local_admin["profession"], "Doctor")
        self.assertEqual(local_admin["tenantOwnerName"], "Property Owner")
        self.assertEqual(backend_portal._public_resident(opted_in_row, None)["profession"], "Doctor")

        worker_resident = cloudflare_app._public_resident(private_row, None)
        self.assertNotIn("profession", worker_resident)
        self.assertNotIn("tenantOwnerName", worker_resident)
        self.assertNotIn("publicProfessionalListing", worker_resident)
        worker_admin = cloudflare_app._public_resident(private_row, None, include_private=True)
        self.assertEqual(worker_admin["profession"], "Doctor")
        self.assertEqual(worker_admin["tenantOwnerName"], "Property Owner")
        self.assertEqual(cloudflare_app._public_resident(opted_in_row, None)["profession"], "Doctor")

    def test_public_directory_projection_is_explicit_and_minimal(self):
        private_row = resident_row(
            profession="Doctor",
            tenantOwnerName="Property Owner",
            publicProfessionalListing=False,
        )
        opted_in_row = {**private_row, "publicProfessionalListing": True}

        self.assertIsNone(backend_portal._public_professional(private_row))
        local_listing = backend_portal._public_professional(opted_in_row)
        self.assertEqual(local_listing, {
            "name": "Resident One",
            "house": "A-1",
            "profession": "Doctor",
            "contact": "9876543210",
        })
        self.assertNotIn("tenantOwnerName", local_listing or {})

    def test_public_contacts_keep_official_and_association_sources_separate(self):
        office_bearers = [
            {"id": "OB-1", "name": "Committee Member", "role": "President", "phone": "9876543210"},
            {"id": "OB-2", "name": "No Phone", "role": "Treasurer", "phone": ""},
        ]
        for contacts in (backend_portal._public_contacts(office_bearers), domain.public_contacts(office_bearers)):
            self.assertEqual({row["number"] for row in contacts if row["source"] == "Official/public"}, {"112", "108", "101", "1912", "1930"})
            association = [row for row in contacts if row["source"] == "Association-maintained"]
            self.assertEqual(len(association), 16)
            numbers = {row["number"] for row in association}
            self.assertTrue({"9876543210", "9448800005", "9980365356", "8277884014", "9620480465", "9535161492", "080-22943703", "9535666127", "9916020005", "9845933067", "080-22971542", "9945439072", "7829822133", "9845080903", "8050529768", "9844616879"}.issubset(numbers))
            self.assertTrue(all(row["kind"] == "local" for row in association))


class _LocalAuth:
    @staticmethod
    def utc_now():
        return datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

    @staticmethod
    def hash_password(password, salt):
        return (password.encode("utf-8") + salt)[:64].ljust(64, b"x")


class ResidentAccountWorkflowTests(unittest.TestCase):
    def test_local_provision_and_reset_still_use_write_only_passwords(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                active INTEGER NOT NULL,
                resident_id TEXT,
                must_change_password INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE sessions (user_id TEXT NOT NULL);
            """
        )
        first = backend_portal._collection(
            "residents",
            [resident_row(profession="Doctor", tenantOwnerName="Property Owner", password="first-password")],
        )[0]

        with patch.object(backend_portal, "_auth", return_value=_LocalAuth):
            self.assertTrue(backend_portal._sync_accounts(connection, first, {"RES-1": "first-password"}, []))
            account = connection.execute("SELECT * FROM users WHERE resident_id = 'RES-1'").fetchone()
            self.assertIsNotNone(account)
            self.assertEqual(account["username"], "9876543210")
            self.assertEqual(account["must_change_password"], 1)

            connection.execute("INSERT INTO sessions(user_id) VALUES (?)", (account["id"],))
            updated = copy.deepcopy(first)
            self.assertNotIn("password", updated[0])
            self.assertTrue(
                backend_portal._sync_accounts(
                    connection,
                    updated,
                    {"RES-1": "second-password"},
                    first,
                )
            )
            reset = connection.execute("SELECT * FROM users WHERE id = ?", (account["id"],)).fetchone()
            self.assertEqual(reset["must_change_password"], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)


class _CloudAccountStore:
    def __init__(self, rows):
        self.rows = rows

    async def all(self, sql, *parameters):
        return copy.deepcopy(self.rows)


class CloudflareResidentAccountWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_provision_and_reset_build_account_statements(self):
        resident = domain.collection(
            "residents",
            [resident_row(profession="Doctor", tenantOwnerName="Property Owner")],
        )[0]

        async def fake_hash(password, salt):
            return b"h" * 64

        with patch.object(cloudflare_app, "hash_password", new=fake_hash):
            store = _CloudAccountStore([])
            statements, changed = await cloudflare_app._sync_accounts(
                store,
                resident,
                {"RES-1": "first-password"},
                [],
                "2026-10-22T12:00:00+00:00",
            )
            self.assertTrue(changed)
            self.assertTrue(any("INSERT INTO users" in sql for sql, _ in statements))
            self.assertTrue(all("first-password" not in repr(parameters) for _, parameters in statements))

            account = {
                "id": "USR-RES-1",
                "username": "9876543210",
                "display_name": "Resident One",
                "role": "resident",
                "active": 1,
                "resident_id": "RES-1",
                "must_change_password": 1,
            }
            reset_store = _CloudAccountStore([account])
            statements, changed = await cloudflare_app._sync_accounts(
                reset_store,
                resident,
                {"RES-1": "second-password"},
                resident,
                "2026-10-22T12:00:00+00:00",
            )
            self.assertTrue(changed)
            self.assertTrue(any("password_hash" in sql for sql, _ in statements))
            self.assertTrue(any("DELETE FROM sessions" in sql for sql, _ in statements))
            self.assertTrue(all("second-password" not in repr(parameters) for _, parameters in statements))


if __name__ == "__main__":
    unittest.main()
