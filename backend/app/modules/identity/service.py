from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security.jwt import AccessTokenSettings, create_access_token
from app.core.security.password import PasswordValidationError, hash_password, verify_password
from app.core.security.tokens import OpaqueRefreshToken, generate_refresh_token
from app.modules.identity.exceptions import EmailAlreadyRegisteredError, InvalidCredentialsError
from app.modules.identity.models import RefreshToken, RefreshTokenFamily, User
from app.modules.identity.repository import (
    add_initial_session,
    add_user,
    find_user_by_email,
    find_user_by_id,
)
from app.modules.identity.schemas import (
    CurrentUserResponse,
    LoginRequest,
    RegisteredUserResponse,
    RegistrationRequest,
    normalize_email,
)

_MYSQL_DUPLICATE_KEY = 1062
_EMAIL_UNIQUE_CONSTRAINT = "uq_users_email_normalized"
_MYSQL_DUPLICATE_KEY_PATTERN = re.compile(r"\bfor key\s+['`]([^'`]+)['`]", re.IGNORECASE)
REFRESH_TOKEN_LIFETIME = timedelta(days=7)
FAMILY_ABSOLUTE_LIFETIME = timedelta(days=30)
FAMILY_RETENTION = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class IssuedSession:
    access_token: str = field(repr=False)
    refresh_token: OpaqueRefreshToken = field(repr=False)


def register_user(request: RegistrationRequest, session: Session) -> RegisteredUserResponse:
    email_normalized = normalize_email(request.email)
    encoded_password = hash_password(request.password)
    timestamp = datetime.now(UTC).replace(tzinfo=None)
    user = User(
        email_normalized=email_normalized,
        full_name=request.full_name,
        password_hash=encoded_password,
        global_role="STUDENT",
        status="ACTIVE",
        created_at=timestamp,
        updated_at=timestamp,
    )

    try:
        if session.in_transaction():
            raise RuntimeError("Registration requires a session without an active transaction")
        with session.begin():
            add_user(session, user)
    except IntegrityError as exc:
        session.rollback()
        if _is_duplicate_email_error(exc):
            raise EmailAlreadyRegisteredError() from exc
        raise

    return RegisteredUserResponse(
        id=user.id,
        email=user.email_normalized,
        full_name=user.full_name,
        global_role="STUDENT",
        status="ACTIVE",
        created_at=user.created_at.replace(tzinfo=UTC),
    )


def _is_duplicate_email_error(exc: IntegrityError) -> bool:
    original = exc.orig
    arguments = getattr(original, "args", ())
    if len(arguments) < 2 or arguments[0] != _MYSQL_DUPLICATE_KEY:
        return False
    match = _MYSQL_DUPLICATE_KEY_PATTERN.search(str(arguments[1]))
    if match is None:
        return False
    key_name = match.group(1).rsplit(".", maxsplit=1)[-1]
    return key_name == _EMAIL_UNIQUE_CONSTRAINT


def login_user(
    request: LoginRequest,
    session: Session,
    access_token_settings: AccessTokenSettings,
) -> IssuedSession:
    email_normalized = normalize_email(request.email)
    user = find_user_by_email(session, email_normalized)
    snapshot = None if user is None else (user.id, user.password_hash, user.status)
    session.rollback()

    if snapshot is None:
        raise InvalidCredentialsError()
    user_id, encoded_password, status = snapshot
    try:
        password_valid = verify_password(request.password, encoded_password)
    except PasswordValidationError:
        password_valid = False
    if not password_valid or status != "ACTIVE":
        raise InvalidCredentialsError()

    issued_at = datetime.now(UTC)
    access_token = create_access_token(str(user_id), access_token_settings, now=issued_at)
    refresh_token = generate_refresh_token()
    database_time = issued_at.replace(tzinfo=None)
    family_id = uuid4().bytes
    family = RefreshTokenFamily(
        id=family_id,
        user_id=user_id,
        created_at=database_time,
        absolute_expires_at=(issued_at + FAMILY_ABSOLUTE_LIFETIME).replace(tzinfo=None),
        revoked_at=None,
        revoke_reason=None,
        suspicious_reuse_at=None,
        purge_after=(issued_at + FAMILY_ABSOLUTE_LIFETIME + FAMILY_RETENTION).replace(tzinfo=None),
    )
    token = RefreshToken(
        family_id=family_id,
        token_hash=refresh_token.digest(),
        created_at=database_time,
        expires_at=(issued_at + REFRESH_TOKEN_LIFETIME).replace(tzinfo=None),
        revoked_at=None,
        last_used_at=None,
        rotated_at=None,
        replaced_by_id=None,
        generation=0,
    )

    if session.in_transaction():
        raise RuntimeError("Login issuance requires a session without an active transaction")
    with session.begin():
        current_user = find_user_by_id(session, user_id)
        if current_user is None or current_user.status != "ACTIVE":
            raise InvalidCredentialsError()
        add_initial_session(session, family, token)

    return IssuedSession(access_token=access_token, refresh_token=refresh_token)


def current_user_response(user: User) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user.id,
        email=user.email_normalized,
        full_name=user.full_name,
        global_role=user.global_role,
        status="ACTIVE",
    )
