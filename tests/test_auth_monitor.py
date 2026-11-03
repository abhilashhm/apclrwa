import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("APCLRWA_ENV", "development")
os.environ.setdefault("APCLRWA_CORS_ORIGINS", "http://localhost:5173")

from backend import auth as local_auth
from cloudflare import auth as worker_auth


class LocalAuthenticationMonitorTests(unittest.TestCase):
    def test_monitor_returns_aggregate_failure_data_without_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "portal.sqlite3"
            with patch.object(local_auth, "DATABASE_PATH", database_path), \
                 patch.object(local_auth, "AUTH_WINDOW_SECONDS", 900), \
                 patch.object(local_auth, "AUTH_ALERT_FAILURES", 2):
                local_auth.initialize_database()
                with local_auth.database() as connection:
                    connection.executemany(
                        "INSERT INTO auth_attempts(id, account_key, ip_key, attempted_at, outcome) VALUES (?, ?, ?, ?, ?)",
                        [
                            ("ATT-1", b"account-one", b"ip-one", 1_000_000_000, "failed"),
                            ("ATT-2", b"account-one", b"ip-one", 1_000_000_001, "cleared"),
                            ("ATT-3", b"account-two", b"ip-two", 1_000_000_002, "succeeded"),
                        ],
                    )
                with patch.object(local_auth.time, "time", return_value=1_000_000_100):
                    summary = local_auth.authentication_monitor()
            self.assertTrue(summary["alert"])
            self.assertEqual(summary["failureCount"], 2)
            self.assertEqual(summary["activeFailureCount"], 1)
            self.assertEqual(summary["succeededCount"], 1)
            self.assertNotIn("accountKey", summary)
            self.assertNotIn("ipKey", summary)
            self.assertNotIn("password", summary)
            self.assertEqual(len(summary["recentFailures"]), 2)


class WorkerAuthenticationMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_monitor_uses_only_aggregate_and_timestamp_fields(self):
        class FakeStore:
            async def all(self, sql, *parameters):
                if "GROUP BY outcome" in sql:
                    return [
                        {"outcome": "failed", "count": 3},
                        {"outcome": "succeeded", "count": 1},
                    ]
                return [{"attempted_at": 1_000_000_010, "outcome": "failed"}]

        class Env:
            APCLRWA_AUTH_WINDOW_SECONDS = "900"
            APCLRWA_AUTH_ALERT_FAILURES = "3"

        with patch.object(worker_auth.time, "time", return_value=1_000_000_100):
            summary = await worker_auth.authentication_monitor(FakeStore(), Env())
        self.assertTrue(summary["alert"])
        self.assertEqual(summary["failureCount"], 3)
        self.assertEqual(summary["activeFailureCount"], 3)
        self.assertEqual(summary["recentFailures"][0]["outcome"], "failed")
        self.assertNotIn("accountKey", summary)
        self.assertNotIn("ipKey", summary)


if __name__ == "__main__":
    unittest.main()
