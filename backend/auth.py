"""FastAPI authentication service and private local Tally snapshot bridge.

Authentication is database-backed. Operational financial records are still
stored in browser localStorage; the Tally endpoint serves a read-only import
snapshot and does not make that snapshot the authoritative accounting ledger.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APCLRWA_DATA_DIR", PROJECT_ROOT / "data"))
DATABASE_PATH = Path(os.environ.get("APCLRWA_DATABASE_PATH", DATA_DIR / "apclrwa.sqlite3"))
SESSION_COOKIE = "apclrwa_session"
SESSION_HOURS = int(os.environ.get("APCLRWA_SESSION_HOURS", "12"))
COOKIE_SECURE = os.environ.get("APCLRWA_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes"}
PASSWORD_N = 2**14
PASSWORD_R = 8
PASSWORD_P = 1
PASSWORD_DKLEN = 64

DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174"
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("APCLRWA_CORS_ORIGINS", DEFAULT_ORIGINS).split(",")
    if origin.strip()
]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=1024)
    role: str = Field(default="committee", pattern="^(committee|resident)$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('committee', 'resident')),
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash BLOB PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
            """
        )
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (utc_now().isoformat(),))


def hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=PASSWORD_N,
        r=PASSWORD_R,
        p=PASSWORD_P,
        dklen=PASSWORD_DKLEN,
    )


def hash_session_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(row["id"]),
        "username": str(row["username"]),
        "displayName": str(row["display_name"]),
        "role": str(row["role"]),
    }


def get_authenticated_user(request: Request) -> dict[str, str]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")

    with database() as connection:
        row = connection.execute(
            """
            SELECT users.id, users.username, users.display_name, users.role
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ? AND users.active = 1
            """,
            (hash_session_token(token), utc_now().isoformat()),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired. Sign in again.")
    return public_user(row)


def require_committee(user: dict[str, str] = Depends(get_authenticated_user)) -> dict[str, str]:
    if user["role"] != "committee":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Committee access is required.")
    return user


app = FastAPI(title="APCLRWA Portal API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.on_event("startup")
def startup() -> None:
    initialize_database()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    if payload.role == "resident":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Resident accounts are not available yet. They must be provisioned in the backend first.",
        )

    username = payload.username.strip().casefold()
    with database() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE username = ? AND active = 1",
            (username,),
        ).fetchone()

        # Do comparable work for unknown accounts to reduce username timing leaks.
        if row is None:
            salt = bytes(16)
            hash_password(payload.password, salt)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Username or password is incorrect.")

        candidate = hash_password(payload.password, bytes(row["password_salt"]))
        if not hmac.compare_digest(candidate, bytes(row["password_hash"])):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Username or password is incorrect.")

        token = secrets.token_urlsafe(32)
        now = utc_now()
        expires_at = now + timedelta(hours=SESSION_HOURS)
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(),))
        connection.execute(
            "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (hash_session_token(token), row["id"], expires_at.isoformat(), now.isoformat()),
        )
        user = public_user(row)

    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_HOURS * 60 * 60,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/api",
    )
    return {"user": user, "expiresAt": expires_at.isoformat()}


@app.get("/api/auth/me")
def current_session(user: dict[str, str] = Depends(get_authenticated_user)) -> dict[str, Any]:
    return {"user": user}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with database() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_session_token(token),))
    response.delete_cookie(key=SESSION_COOKIE, path="/api", httponly=True, secure=COOKIE_SECURE, samesite="lax")
    return {"status": "signed out"}


@app.get("/api/admin/session")
def committee_session(user: dict[str, str] = Depends(require_committee)) -> dict[str, Any]:
    return {"user": user, "authorized": True}


@app.get("/api/admin/tally-import")
def tally_import(user: dict[str, str] = Depends(require_committee)) -> dict[str, Any]:
    """Return the private, locally reconciled Tally snapshot to committee users."""
    import_path = DATA_DIR / "tally-import.json"
    try:
        return json.loads(import_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No local Tally import is available.") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="The local Tally import could not be read.") from exc
