"""Generate a one-time, hashed committee-admin INSERT for remote D1.

The password is read interactively and never written to stdout. Redirect the
SQL output to a private temporary file, execute it with Wrangler, and remove
the file afterward. This is intentionally separate from the local SQLite
``backend.cli`` command because Worker passwords use the PBKDF2 format exposed
by the Cloudflare runtime.
"""

from __future__ import annotations

import getpass
import hashlib
import secrets
import sys
from datetime import datetime, timezone


PASSWORD_ITERATIONS = 100_000
PASSWORD_DKLEN = 64


def _prompt(label: str) -> str:
    sys.stderr.write(label)
    sys.stderr.flush()
    value = sys.stdin.readline()
    if not value:
        raise SystemExit("Input was cancelled.")
    return value.rstrip("\r\n")


def _sql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main() -> int:
    username = _prompt("Committee admin username: ").strip().casefold()
    if not username or len(username) > 120 or any(character.isspace() for character in username):
        raise SystemExit("Use a username without spaces (up to 120 characters).")
    password = getpass.getpass("New password (12-1024 characters): ", stream=sys.stderr)
    confirmation = getpass.getpass("Confirm password: ", stream=sys.stderr)
    if not 12 <= len(password) <= 1024:
        raise SystemExit("Password must be between 12 and 1024 characters.")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS, PASSWORD_DKLEN)
    user_id = "USR-" + secrets.token_urlsafe(18)
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    print(
        "INSERT INTO users(id, username, display_name, role, password_salt, password_hash, "
        "active, resident_id, must_change_password, created_at, password_scheme) VALUES ("
        f"{_sql(user_id)}, {_sql(username)}, {_sql(username)}, 'committee', "
        f"{_sql(salt.hex())}, {_sql(password_hash.hex())}, 1, NULL, 0, "
        f"{_sql(created_at)}, 'pbkdf2-sha256');"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
