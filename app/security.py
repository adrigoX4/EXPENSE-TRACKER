"""Password hashing, signed session cookies, validation and login throttling."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from collections import defaultdict

from fastapi import Request, Response

from app import accounts
from app.config import settings
from app.errors import AppError, ValidationError

COOKIE_NAME = "cartflow_session"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

_attempts: dict[str, list[float]] = defaultdict(list)
_attempt_lock = threading.Lock()
_dummy_hash: str | None = None


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def validate_email(value: str) -> str:
    email = normalize_email(value)
    if not email or len(email) > 254 or not EMAIL_PATTERN.match(email):
        raise ValidationError("Enter a valid email address, for example name@example.com.")
    return email


def validate_password(value: str) -> str:
    password = value or ""
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValidationError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters.")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValidationError(f"Password must be at most {PASSWORD_MAX_LENGTH} characters.")
    if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
        raise ValidationError("Password must include at least one letter and one number.")
    return password


def hash_password(password: str, *, iterations: int | None = None) -> str:
    rounds = max(100, int(iterations or settings.password_iterations))
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return f"pbkdf2_sha256${rounds}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not password:
        return False
    try:
        scheme, rounds_text, salt_text, digest_text = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        rounds = int(rounds_text)
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
    except (ValueError, TypeError):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(candidate, expected)


def dummy_verify(password: str) -> None:
    """Spend comparable time when an email is unknown, to blur account probing."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("cartflow-timing-placeholder-1")
    verify_password(password, _dummy_hash)


def _sign(payload: bytes) -> str:
    key = accounts.get_or_create_secret().encode("utf-8")
    return _b64encode(hmac.new(key, payload, hashlib.sha256).digest())


def create_session_token(account_id: str, *, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    expires = issued + max(1, settings.session_days) * 86400
    payload = json.dumps(
        {"uid": account_id, "iat": issued, "exp": expires},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    body = _b64encode(payload)
    return f"v1.{body}.{_sign(payload)}"


def read_session_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        version, body, signature = token.split(".", 2)
        if version != "v1":
            return None
        payload = _b64decode(body)
        if not hmac.compare_digest(signature, _sign(payload)):
            return None
        data = json.loads(payload.decode("utf-8"))
        if int(data.get("exp", 0)) < int(time.time()):
            return None
        account_id = str(data.get("uid") or "")
        return account_id or None
    except (ValueError, TypeError, KeyError):
        return None


def user_from_request(request: Request) -> accounts.AccountUser | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    account_id = read_session_token(token)
    if not account_id:
        return None
    return accounts.get_account(account_id)


def current_user(request: Request) -> accounts.AccountUser:
    user = getattr(request.state, "user", None)
    if user is None:
        raise AppError("Sign in to continue.", code="authentication_required", status_code=401)
    return user


def set_session_cookie(response: Response, request: Request, account_id: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        create_session_token(account_id),
        max_age=max(1, settings.session_days) * 86400,
        httponly=True,
        samesite="lax",
        secure=bool(settings.cookie_secure or request.url.scheme == "https"),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")


def client_key(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return host


def guard_attempts(key: str, *, limit: int, window_seconds: int) -> None:
    cutoff = time.monotonic() - window_seconds
    with _attempt_lock:
        bucket = [stamp for stamp in _attempts[key] if stamp > cutoff]
        _attempts[key] = bucket
        if len(bucket) >= limit:
            raise AppError(
                "Too many attempts. Wait a few minutes and try again.",
                code="rate_limited",
                status_code=429,
            )


def record_attempt(key: str) -> None:
    with _attempt_lock:
        _attempts[key].append(time.monotonic())


def clear_attempts(key: str) -> None:
    with _attempt_lock:
        _attempts.pop(key, None)


def reset_rate_limits() -> None:
    with _attempt_lock:
        _attempts.clear()
