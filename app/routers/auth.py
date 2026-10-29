from __future__ import annotations

import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response, status

from app import accounts, security, userdata
from app.config import BASE_DIR, settings
from app.errors import AppError, ConflictError, ValidationError
from app.schemas import AuthCredentials, AuthStatusOut, AuthUserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

_registration_lock = threading.Lock()


def _stored_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BASE_DIR))
    except ValueError:
        return str(path.resolve())


def _public(account: accounts.AccountUser) -> AuthUserOut:
    return AuthUserOut(
        id=account.id,
        email=account.email,
        is_owner=account.is_owner,
        created_at=account.created_at,
    )


@router.get("/status", response_model=AuthStatusOut)
def auth_status(request: Request):
    has_accounts = accounts.accounts_exist()
    return AuthStatusOut(
        has_accounts=has_accounts,
        allow_signup=settings.allow_signup or not has_accounts,
        authenticated=getattr(request.state, "user", None) is not None,
    )


@router.get("/me", response_model=AuthUserOut)
def me(user: accounts.AccountUser = Depends(security.current_user)):
    return _public(user)


@router.post("/register", response_model=AuthUserOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: AuthCredentials,
    request: Request,
    response: Response,
):
    email = security.validate_email(payload.email)
    security.validate_password(payload.password)

    has_accounts = accounts.accounts_exist()
    if not settings.allow_signup and has_accounts:
        raise AppError(
            "New accounts are disabled on this server.",
            code="signup_disabled",
            status_code=403,
        )

    limit_key = f"register:{security.client_key(request)}"
    security.guard_attempts(limit_key, limit=5, window_seconds=3600)
    security.record_attempt(limit_key)

    password_hash = security.hash_password(payload.password)
    account_id = uuid.uuid4().hex

    with _registration_lock:
        if accounts.get_account_by_email(email) is not None:
            raise ConflictError(
                "An account with this email already exists. Sign in instead.",
                code="email_taken",
            )
        first_account = not accounts.accounts_exist()
        if first_account:
            data_path = userdata.default_database_path()
        else:
            data_path = userdata.new_data_file(account_id)
        created_file = not data_path.exists()

        try:
            userdata.ensure_user_database(data_path)
            account = accounts.create_account(
                account_id=account_id,
                email=email,
                password_hash=password_hash,
                data_file=_stored_path(data_path),
                is_owner=first_account,
            )
        except ValueError as exc:
            raise ConflictError(
                "An account with this email already exists. Sign in instead.",
                code="email_taken",
            ) from exc
        except Exception as exc:
            if created_file and not first_account:
                data_path.unlink(missing_ok=True)
            raise AppError(
                "The account could not be created. Check the server log and try again.",
                code="account_creation_failed",
                status_code=500,
            ) from exc

    security.clear_attempts(limit_key)
    security.set_session_cookie(response, request, account.id)
    return _public(account)


@router.post("/login", response_model=AuthUserOut)
def login(payload: AuthCredentials, request: Request, response: Response):
    email = security.normalize_email(payload.email)
    password = payload.password or ""
    if not email:
        raise ValidationError("Enter your email address.")

    limit_key = f"login:{security.client_key(request)}:{email}"
    security.guard_attempts(limit_key, limit=8, window_seconds=900)

    account = accounts.get_account_by_email(email)
    stored_hash = accounts.get_password_hash(email)
    if account is None or stored_hash is None:
        security.dummy_verify(password)
        security.record_attempt(limit_key)
        raise AppError(
            "Email or password is incorrect.",
            code="invalid_credentials",
            status_code=401,
        )
    if not security.verify_password(password, stored_hash):
        security.record_attempt(limit_key)
        raise AppError(
            "Email or password is incorrect.",
            code="invalid_credentials",
            status_code=401,
        )

    try:
        userdata.ensure_user_database(userdata.resolve_data_file(account))
    except Exception as exc:
        raise AppError(
            "This account's database could not be opened. Check the server log.",
            code="account_database_unavailable",
            status_code=500,
        ) from exc

    accounts.touch_login(account.id)
    security.clear_attempts(limit_key)
    security.set_session_cookie(response, request, account.id)
    return _public(account)


@router.post("/logout")
def logout(response: Response):
    security.clear_session_cookie(response)
    return {"ok": True}
