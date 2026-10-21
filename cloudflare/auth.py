"""Authentication helpers for the Cloudflare Worker path.

This module intentionally does not import the local FastAPI/SQLite module. The
same password/session formats are used, but all persistence is performed by
the async D1 adapter.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request, Response, status
from pydantic import BaseModel, Field

try:
    from .d1 import D1Conflict, D1Store
except ImportError:
    from d1 import D1Conflict, D1Store


SESSION_COOKIE = "apclrwa_session"
PASSWORD_N = 2**14
PASSWORD_R = 8
PASSWORD_P = 1
PASSWORD_DKLEN = 64
PASSWORD_SCHEME = "pbkdf2-sha256"
# Cloudflare's Python Workers Web Crypto binding rejects PBKDF2 iteration
# counts above 100,000. Keep this value explicit and in sync with the one-time
# bootstrap generator and the stored password-scheme label.
PASSWORD_ITERATIONS = 100_000


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=1024)
    role: str = Field(default="committee", pattern="^(committee|resident)$")


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(alias="currentPassword", min_length=1, max_length=1024)
    new_password: str = Field(alias="newPassword", min_length=12, max_length=1024)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def setting(env: Any, name: str, default: str) -> str:
    value = getattr(env, name, default)
    if value is None:
        return default
    return str(value)


def integer_setting(env: Any, name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(setting(env, name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}.") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


def boolean_setting(env: Any, name: str, default: bool) -> bool:
    value = setting(env, name, str(default)).strip().lower()
    if value not in {"1", "true", "yes", "0", "false", "no"}:
        raise ValueError(f"{name} must be true or false.")
    return value in {"1", "true", "yes"}


async def hash_password(password: str, salt: bytes) -> bytes:
    """Derive the Worker password hash with Web Crypto PBKDF2.

    Pyodide does not expose the CPython ``hashlib`` KDF helpers used by the
    local SQLite service. Workers exposes PBKDF2 through ``crypto.subtle``;
    the local fallback keeps the same bytes for deterministic tests and seed
    tooling.
    """
    pbkdf2 = getattr(hashlib, "pbkdf2_hmac", None)
    if pbkdf2 is not None:
        return pbkdf2("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS, PASSWORD_DKLEN)
    from js import Object, Uint8Array, crypto
    from pyodide.ffi import to_js

    password_bytes = Uint8Array.new(password.encode("utf-8"))
    salt_bytes = Uint8Array.new(salt)
    key = await crypto.subtle.importKey(
        "raw",
        password_bytes.buffer,
        to_js({"name": "PBKDF2"}, dict_converter=Object.fromEntries),
        False,
        to_js(["deriveBits"]),
    )
    derived = await crypto.subtle.deriveBits(
        to_js(
            {"name": "PBKDF2", "salt": salt_bytes.buffer, "iterations": PASSWORD_ITERATIONS, "hash": "SHA-256"},
            dict_converter=Object.fromEntries,
        ),
        key,
        PASSWORD_DKLEN * 8,
    )
    return Uint8Array.new(derived).to_bytes()


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_user(row: dict[str, Any]) -> dict[str, Any]:
    user: dict[str, Any] = {
        "id": str(row["id"]),
        "username": str(row["username"]),
        "displayName": str(row["display_name"]),
        "role": str(row["role"]),
        "tempPassword": bool(row.get("must_change_password")),
    }
    if row.get("resident_id") is not None:
        user["residentId"] = str(row["resident_id"])
    return user


async def password_matches(row: dict[str, Any] | None, password: str) -> bool:
    salt = bytes.fromhex(str(row["password_salt"])) if row is not None else bytes(16)
    expected = bytes.fromhex(str(row["password_hash"])) if row is not None else bytes(PASSWORD_DKLEN)
    scheme = str(row.get("password_scheme", PASSWORD_SCHEME)) if row is not None else PASSWORD_SCHEME
    candidate = await hash_password(password, salt) if scheme == PASSWORD_SCHEME else bytes(PASSWORD_DKLEN)
    return hmac.compare_digest(candidate, expected) and row is not None


def unchanged_password(before: dict[str, Any], after: dict[str, Any] | None) -> bool:
    return (
        after is not None
        and hmac.compare_digest(str(before["password_hash"]), str(after["password_hash"]))
        and hmac.compare_digest(str(before["password_salt"]), str(after["password_salt"]))
    )


def client_ip(request: Request) -> str:
    client = request.scope.get("client")
    if isinstance(client, (tuple, list)) and client:
        return str(client[0])
    if isinstance(client, str):
        return client
    cloudflare = request.scope.get("cf")
    if isinstance(cloudflare, dict) and cloudflare.get("connecting_ip"):
        return str(cloudflare["connecting_ip"])
    return "unknown"


async def reserve_password_attempt(store: D1Store, request: Request, env: Any, username: str) -> str:
    account_limit = integer_setting(env, "APCLRWA_AUTH_ACCOUNT_LIMIT", 5, 1, 100)
    ip_limit = integer_setting(env, "APCLRWA_AUTH_IP_LIMIT", 30, 1, 10000)
    window_seconds = integer_setting(env, "APCLRWA_AUTH_WINDOW_SECONDS", 900, 60, 86400)
    account_key = hashlib.sha256(username.strip().casefold().encode("utf-8")).hexdigest()
    ip_key = hashlib.sha256(client_ip(request).encode("utf-8")).hexdigest()
    now = time.time()
    cutoff = now - window_seconds
    attempt_id = secrets.token_hex(16)
    account_count = await store.first(
        "SELECT COUNT(*) AS count FROM auth_attempts WHERE account_key = ? AND outcome IN ('pending', 'failed') AND attempted_at > ?",
        account_key,
        cutoff,
    )
    ip_count = await store.first(
        "SELECT COUNT(*) AS count FROM auth_attempts WHERE ip_key = ? AND attempted_at > ?",
        ip_key,
        cutoff,
    )
    account_total = int(account_count["count"]) if account_count else 0
    ip_total = int(ip_count["count"]) if ip_count else 0
    retry_after = 0
    if account_total >= account_limit:
        oldest = await store.first(
            "SELECT attempted_at FROM auth_attempts WHERE account_key = ? AND outcome IN ('pending', 'failed') AND attempted_at > ? ORDER BY attempted_at LIMIT 1 OFFSET ?",
            account_key,
            cutoff,
            max(0, account_total - account_limit),
        )
        if oldest:
            retry_after = max(retry_after, max(1, math.ceil(float(oldest["attempted_at"]) + window_seconds - now)))
    if ip_total >= ip_limit:
        oldest = await store.first(
            "SELECT attempted_at FROM auth_attempts WHERE ip_key = ? AND attempted_at > ? ORDER BY attempted_at LIMIT 1 OFFSET ?",
            ip_key,
            cutoff,
            max(0, ip_total - ip_limit),
        )
        if oldest:
            retry_after = max(retry_after, max(1, math.ceil(float(oldest["attempted_at"]) + window_seconds - now)))
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    try:
        await store.batch([
            ("DELETE FROM auth_attempts WHERE attempted_at <= ?", (cutoff,)),
            ("DELETE FROM auth_attempt_guard WHERE id = 1", ()),
            ("INSERT INTO auth_attempt_guard(id, account_key, ip_key, cutoff, account_limit, ip_limit) VALUES (1, ?, ?, ?, ?, ?)", (account_key, ip_key, cutoff, account_limit, ip_limit)),
            ("INSERT INTO auth_attempts(id, account_key, ip_key, attempted_at, outcome) VALUES (?, ?, ?, ?, 'pending')", (attempt_id, account_key, ip_key, now)),
            ("DELETE FROM auth_attempt_guard WHERE id = 1", ()),
        ])
    except D1Conflict:
        raise HTTPException(status_code=429, detail="Too many authentication attempts. Try again later.") from None
    return attempt_id


async def mark_failed(store: D1Store, attempt_id: str) -> None:
    await store.run("UPDATE auth_attempts SET outcome = 'failed' WHERE id = ?", attempt_id)


async def authenticated_user(store: D1Store, request: Request) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token or len(token) > 256:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")
    row = await store.first(
        """
        SELECT users.id, users.username, users.display_name, users.role,
               users.resident_id, users.must_change_password
        FROM sessions JOIN users ON users.id = sessions.user_id
        WHERE sessions.token_hash = ? AND sessions.expires_at > ? AND users.active = 1
        """,
        hash_session_token(token),
        utc_now().isoformat(),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired. Sign in again.")
    request.state.authenticated = True
    return public_user(row)


async def require_committee(store: D1Store, request: Request) -> dict[str, Any]:
    user = await authenticated_user(store, request)
    if user["role"] != "committee":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Committee access is required.")
    return user


def session_cookie(response: Response, token: str, env: Any) -> None:
    hours = integer_setting(env, "APCLRWA_SESSION_HOURS", 12, 1, 168)
    secure = boolean_setting(env, "APCLRWA_COOKIE_SECURE", True)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=hours * 60 * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/api",
    )


def clear_session_cookie(response: Response, env: Any) -> None:
    secure = boolean_setting(env, "APCLRWA_COOKIE_SECURE", True)
    response.delete_cookie(key=SESSION_COOKIE, path="/api", httponly=True, secure=secure, samesite="lax")
