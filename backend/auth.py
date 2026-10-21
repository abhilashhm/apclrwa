"""Database-backed authentication and the private local Tally snapshot bridge.

HTTPS and explicit origins are required by default. Local HTTP development must
opt in with APCLRWA_ENV=development. Proxy headers are deliberately not parsed
here: deployments must configure Uvicorn's trusted proxy addresses explicitly.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APCLRWA_DATA_DIR", PROJECT_ROOT / "data"))
DATABASE_PATH = Path(os.environ.get("APCLRWA_DATABASE_PATH", DATA_DIR / "apclrwa.sqlite3"))
SESSION_COOKIE = "apclrwa_session"
PASSWORD_N = 2**14
PASSWORD_R = 8
PASSWORD_P = 1
PASSWORD_DKLEN = 64


def _integer_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}.") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _boolean_setting(name: str, default: bool) -> bool:
    value = os.environ.get(name, str(default)).strip().lower()
    if value not in {"1", "true", "yes", "0", "false", "no"}:
        raise ValueError(f"{name} must be true or false.")
    return value in {"1", "true", "yes"}


ENVIRONMENT = os.environ.get("APCLRWA_ENV", "production").strip().lower()
if ENVIRONMENT not in {"production", "development"}:
    raise ValueError("APCLRWA_ENV must be production or development.")
IS_PRODUCTION = ENVIRONMENT == "production"
SESSION_HOURS = _integer_setting("APCLRWA_SESSION_HOURS", 12, 1, 168)
COOKIE_SECURE = _boolean_setting("APCLRWA_COOKIE_SECURE", IS_PRODUCTION)
if IS_PRODUCTION and not COOKIE_SECURE:
    raise ValueError("Production requires APCLRWA_COOKIE_SECURE=true and HTTPS.")

# Login and password changes share both budgets. Successful checks still count
# against the IP budget; in-flight checks count against the account budget.
AUTH_ACCOUNT_LIMIT = _integer_setting("APCLRWA_AUTH_ACCOUNT_LIMIT", 5, 1, 100)
AUTH_IP_LIMIT = _integer_setting("APCLRWA_AUTH_IP_LIMIT", 30, 1, 10000)
AUTH_WINDOW_SECONDS = _integer_setting("APCLRWA_AUTH_WINDOW_SECONDS", 900, 60, 86400)

DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174"
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.IGNORECASE)


def _validated_origin(origin: str) -> str:
    """Return a canonical, exact origin; never accept wildcard or URL patterns."""
    if not origin or "*" in origin or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in origin):
        raise ValueError("APCLRWA_CORS_ORIGINS must contain exact HTTP(S) origins.")
    try:
        parsed = urlsplit(origin)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("APCLRWA_CORS_ORIGINS contains an invalid origin.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or origin.endswith((":", "?", "#"))
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError("APCLRWA_CORS_ORIGINS must contain origins, without paths or credentials.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if len(host) > 253 or not all(_HOST_LABEL.fullmatch(label) for label in host.split(".")):
            raise ValueError("APCLRWA_CORS_ORIGINS contains an invalid hostname.")
        canonical_host = host.lower()
        is_loopback = canonical_host == "localhost"
    else:
        if "%" in host:
            raise ValueError("APCLRWA_CORS_ORIGINS does not accept scoped IP addresses.")
        canonical_host = f"[{address.compressed}]" if address.version == 6 else address.compressed
        is_loopback = address.is_loopback
    if parsed.scheme == "http" and (IS_PRODUCTION or not is_loopback):
        raise ValueError("HTTP origins require development mode and a localhost/loopback address.")
    default_port = 443 if parsed.scheme == "https" else 80
    port_suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parsed.scheme}://{canonical_host}{port_suffix}"


_origins_setting = os.environ.get("APCLRWA_CORS_ORIGINS", "" if IS_PRODUCTION else DEFAULT_ORIGINS)
if not _origins_setting.strip():
    raise ValueError("Set APCLRWA_CORS_ORIGINS to an explicit comma-separated list of allowed origins.")
_configured_origins = _origins_setting.split(",")
if any(not origin.strip() for origin in _configured_origins):
    raise ValueError("APCLRWA_CORS_ORIGINS contains an empty origin.")
ALLOWED_ORIGINS = list(dict.fromkeys(_validated_origin(origin.strip()) for origin in _configured_origins))


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=1024)
    role: str = Field(default="committee", pattern="^(committee|resident)$")


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(alias="currentPassword", min_length=1, max_length=1024)
    new_password: str = Field(alias="newPassword", min_length=12, max_length=1024)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
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
                resident_id TEXT,
                must_change_password INTEGER NOT NULL DEFAULT 0,
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
            CREATE TABLE IF NOT EXISTS auth_attempts (
                id TEXT PRIMARY KEY,
                account_key BLOB NOT NULL,
                ip_key BLOB NOT NULL,
                attempted_at REAL NOT NULL,
                outcome TEXT NOT NULL CHECK (outcome IN ('pending', 'failed', 'succeeded', 'cleared'))
            );
            CREATE INDEX IF NOT EXISTS idx_auth_attempts_account
                ON auth_attempts(account_key, outcome, attempted_at);
            CREATE INDEX IF NOT EXISTS idx_auth_attempts_ip ON auth_attempts(ip_key, attempted_at);
            CREATE INDEX IF NOT EXISTS idx_auth_attempts_expiry ON auth_attempts(attempted_at);
            """
        )
        # Serialize migrations across startup workers. Existing committee rows
        # retain their credentials, role and activation state.
        connection.execute("BEGIN IMMEDIATE")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
        if "resident_id" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN resident_id TEXT")
        if "must_change_password" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (utc_now().isoformat(),))
        connection.execute("DELETE FROM auth_attempts WHERE attempted_at <= ?", (time.time() - AUTH_WINDOW_SECONDS,))


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


def public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    user: dict[str, Any] = {
        "id": str(row["id"]),
        "username": str(row["username"]),
        "displayName": str(row["display_name"]),
        "role": str(row["role"]),
        "tempPassword": bool(row["must_change_password"]),
    }
    if row["resident_id"] is not None:
        user["residentId"] = str(row["resident_id"])
    return user


def get_authenticated_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token or len(token) > 256:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")

    with database() as connection:
        row = connection.execute(
            """
            SELECT users.id, users.username, users.display_name, users.role,
                   users.resident_id, users.must_change_password
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ? AND users.active = 1
            """,
            (hash_session_token(token), utc_now().isoformat()),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired. Sign in again.")
    request.state.authenticated = True
    return public_user(row)


def require_committee(user: dict[str, Any] = Depends(get_authenticated_user)) -> dict[str, Any]:
    if user["role"] != "committee":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Committee access is required.")
    return user


def _account_key(username: str) -> bytes:
    return hashlib.sha256(username.strip().casefold().encode("utf-8")).digest()


def _reserve_password_attempt(request: Request, username: str) -> str:
    """Commit a reservation before hashing, without holding a DB lock to hash.

    The ASGI client address is supplied by the server. Never inspect forwarded
    headers here; Uvicorn must be configured to trust only the real proxy peers.
    Even a crashed worker leaves its reservation consuming budget until expiry.
    """
    client_ip = request.client.host if request.client is not None else "unknown"
    ip_key = hashlib.sha256(client_ip.encode("utf-8")).digest()
    account_key = _account_key(username)
    now = time.time()
    cutoff = now - AUTH_WINDOW_SECONDS
    attempt_id = secrets.token_hex(16)
    retry_after = 0
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM auth_attempts WHERE attempted_at <= ?", (cutoff,))
        buckets = (
            ("account_key = ? AND outcome IN ('pending', 'failed')", account_key, AUTH_ACCOUNT_LIMIT),
            ("ip_key = ?", ip_key, AUTH_IP_LIMIT),
        )
        for condition, key, limit in buckets:
            count = connection.execute(
                f"SELECT COUNT(*) FROM auth_attempts WHERE {condition}", (key,)
            ).fetchone()[0]
            if count >= limit:
                # If a configuration change reduced a limit, enough records
                # must expire to get below the new limit, not just the first.
                expires = connection.execute(
                    f"SELECT attempted_at FROM auth_attempts WHERE {condition} "
                    "ORDER BY attempted_at LIMIT 1 OFFSET ?",
                    (key, count - limit),
                ).fetchone()[0] + AUTH_WINDOW_SECONDS
                retry_after = max(retry_after, max(1, math.ceil(expires - now)))
        if not retry_after:
            connection.execute(
                "INSERT INTO auth_attempts(id, account_key, ip_key, attempted_at, outcome) "
                "VALUES (?, ?, ?, ?, 'pending')",
                (attempt_id, account_key, ip_key, now),
            )
    # Raise only after leaving database(): its exception path rolls back.
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    return attempt_id


def _failed_attempt(attempt_id: str) -> None:
    with database() as connection:
        connection.execute("UPDATE auth_attempts SET outcome = 'failed' WHERE id = ?", (attempt_id,))


def _successful_attempt(connection: sqlite3.Connection, attempt_id: str, username: str) -> None:
    connection.execute("UPDATE auth_attempts SET outcome = 'succeeded' WHERE id = ?", (attempt_id,))
    # Keep all rows for IP accounting. Only prior completed account failures are
    # reset; concurrent pending checks still consume their own reservation.
    connection.execute(
        "UPDATE auth_attempts SET outcome = 'cleared' WHERE account_key = ? AND outcome = 'failed'",
        (_account_key(username),),
    )


def _password_matches(row: sqlite3.Row | None, password: str) -> bool:
    salt = bytes(row["password_salt"]) if row is not None else bytes(16)
    expected = bytes(row["password_hash"]) if row is not None else bytes(PASSWORD_DKLEN)
    candidate = hash_password(password, salt)
    matches = hmac.compare_digest(candidate, expected)
    return row is not None and matches


def _unchanged_password(before: sqlite3.Row, after: sqlite3.Row | None) -> bool:
    return (
        after is not None
        and hmac.compare_digest(bytes(before["password_hash"]), bytes(after["password_hash"]))
        and hmac.compare_digest(bytes(before["password_salt"]), bytes(after["password_salt"]))
    )


app = FastAPI(title="APCLRWA Portal API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    expose_headers=["Retry-After"],
)

# The portal router is imported after the auth app and shared dependency
# functions exist. `backend.portal` resolves its auth dependency lazily, so
# this keeps the authentication/database module free of an import cycle while
# ensuring every process exposes the same server-backed portal API.
from . import portal as portal_api

app.include_router(portal_api.router)


@app.middleware("http")
async def enforce_transport_and_origin(request: Request, call_next: Any) -> Response:
    # request.url.scheme is established by the ASGI server (and its configured
    # trusted proxy middleware), not by arbitrary forwarding headers here.
    if IS_PRODUCTION and request.url.scheme != "https":
        response = JSONResponse(status_code=400, content={"detail": "HTTPS is required."})
    elif (
        request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
        and "origin" in request.headers
        and request.headers["origin"] not in ALLOWED_ORIGINS
    ):
        response = JSONResponse(status_code=403, content={"detail": "This request origin is not allowed."})
    else:
        response = await call_next(request)
    if request.url.path.startswith("/api/") or getattr(request.state, "authenticated", False):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    if IS_PRODUCTION and request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


@app.on_event("startup")
def startup() -> None:
    initialize_database()
    portal_api.initialize_portal()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    username = payload.username.strip().casefold()
    attempt_id = _reserve_password_attempt(request, username)
    with database() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE username = ? AND active = 1",
            (username,),
        ).fetchone()

    matches = _password_matches(row, payload.password)
    if not matches or row is None or row["role"] != payload.role:
        _failed_attempt(attempt_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Username or password is incorrect.")

    user = None
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute("SELECT * FROM users WHERE id = ? AND active = 1", (row["id"],)).fetchone()
        # Do not mint a session against a password changed while scrypt ran.
        if _unchanged_password(row, current) and current["role"] == payload.role:
            token = secrets.token_urlsafe(32)
            now = utc_now()
            expires_at = now + timedelta(hours=SESSION_HOURS)
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(),))
            previous_token = request.cookies.get(SESSION_COOKIE)
            if previous_token and len(previous_token) <= 256:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_session_token(previous_token),))
            connection.execute(
                "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (hash_session_token(token), row["id"], expires_at.isoformat(), now.isoformat()),
            )
            _successful_attempt(connection, attempt_id, username)
            user = public_user(current)
        else:
            connection.execute("UPDATE auth_attempts SET outcome = 'failed' WHERE id = ?", (attempt_id,))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Username or password is incorrect.")

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
def current_session(user: dict[str, Any] = Depends(get_authenticated_user)) -> dict[str, Any]:
    return {"user": user}


@app.post("/api/auth/password")
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_authenticated_user),
) -> dict[str, Any]:
    # Temporary resident sessions intentionally have access to this endpoint.
    attempt_id = _reserve_password_attempt(request, user["username"])
    with database() as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ? AND active = 1", (user["id"],)).fetchone()
    if not _password_matches(row, payload.current_password) or row is None:
        _failed_attempt(attempt_id)
        raise HTTPException(status_code=401, detail="Current password is incorrect.")

    salt = secrets.token_bytes(16)
    password_hash = hash_password(payload.new_password, salt)
    token_hash = hash_session_token(request.cookies[SESSION_COOKIE])
    updated_user = None
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT users.* FROM users JOIN sessions ON users.id = sessions.user_id "
            "WHERE users.id = ? AND users.active = 1 AND sessions.token_hash = ? AND sessions.expires_at > ?",
            (user["id"], token_hash, utc_now().isoformat()),
        ).fetchone()
        if _unchanged_password(row, current):
            connection.execute(
                "UPDATE users SET password_salt = ?, password_hash = ?, must_change_password = 0 WHERE id = ?",
                (salt, password_hash, user["id"]),
            )
            connection.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash <> ?", (user["id"], token_hash))
            _successful_attempt(connection, attempt_id, user["username"])
            updated_user = public_user(connection.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone())
        else:
            connection.execute("UPDATE auth_attempts SET outcome = 'failed' WHERE id = ?", (attempt_id,))
    if updated_user is None:
        raise HTTPException(status_code=401, detail="Your credentials changed. Sign in again.")
    return {"user": updated_user}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    token = request.cookies.get(SESSION_COOKIE)
    if token and len(token) <= 256:
        with database() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_session_token(token),))
    response.delete_cookie(key=SESSION_COOKIE, path="/api", httponly=True, secure=COOKIE_SECURE, samesite="lax")
    return {"status": "signed out"}


@app.get("/api/admin/session")
def committee_session(user: dict[str, Any] = Depends(require_committee)) -> dict[str, Any]:
    return {"user": user, "authorized": True}


@app.get("/api/admin/tally-import")
def tally_import(user: dict[str, Any] = Depends(require_committee)) -> dict[str, Any]:
    """Return the private, locally reconciled Tally snapshot to committee users."""
    import_path = DATA_DIR / "tally-import.json"
    try:
        return json.loads(import_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No local Tally import is available.") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="The local Tally import could not be read.") from exc
