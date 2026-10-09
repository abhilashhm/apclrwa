"""Interactive administrative account setup. Passwords are never CLI args."""

from __future__ import annotations

import getpass
import secrets
import sqlite3
import sys

from backend.auth import database, hash_password, initialize_database, utc_now


def create_admin() -> int:
    initialize_database()
    username = input("Committee admin username: ").strip().casefold()
    if not username or len(username) > 120 or any(ch.isspace() for ch in username):
        print("Use a username without spaces (up to 120 characters).", file=sys.stderr)
        return 2

    password = getpass.getpass("New password (at least 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 12:
        print("Password must be at least 12 characters.", file=sys.stderr)
        return 2
    if password != confirmation:
        print("Passwords do not match.", file=sys.stderr)
        return 2

    salt = secrets.token_bytes(16)
    password_hash = hash_password(password, salt)
    user_id = "USR-" + secrets.token_urlsafe(18)
    try:
        with database() as connection:
            connection.execute(
                """
                INSERT INTO users(id, username, display_name, role, password_salt, password_hash, active, created_at)
                VALUES (?, ?, ?, 'committee', ?, ?, 1, ?)
                """,
                (user_id, username, username, salt, password_hash, utc_now().isoformat()),
            )
    except sqlite3.IntegrityError:
        print("That username already exists.", file=sys.stderr)
        return 2

    print(f"Committee account created for {username}.")
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "create-admin":
        print("Usage: python -m backend.cli create-admin", file=sys.stderr)
        return 2
    return create_admin()


if __name__ == "__main__":
    raise SystemExit(main())
