from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security.jwt import AccessTokenSettings, create_access_token
from app.core.security.password import PasswordValidationError, hash_password, verify_password
from app.core.security.tokens import (
    OpaqueRefreshToken,
    RefreshTokenError,
    generate_refresh_token,
    parse_refresh_token,
)
from app.modules.identity.exceptions import EmailAlreadyRegisteredError, InvalidCredentialsError
from app.modules.identity.models import RefreshToken, RefreshTokenFamily, User
from app.modules.identity.repository import (
    add_initial_session,
    add_user,
    find_refresh_token_by_digest,
    find_user_by_email,
    find_user_by_id,
    lock_refresh_token,
    lock_refresh_token_family,
    rotate_refresh_token,
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


@dataclass(frozen=True, slots=True)
class _PresentedRefreshToken:
    token_id: int
    family_id: bytes
    digest: bytes = field(repr=False)


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


def refresh_session(
    encoded_refresh_token: str,
    session: Session,
    access_token_settings: AccessTokenSettings,
) -> IssuedSession:
    presented = _identify_refresh_token(encoded_refresh_token, session)
    reused = False
    issued: IssuedSession | None = None

    if session.in_transaction():
        raise RuntimeError("Refresh rotation requires a session without an active transaction")
    with session.begin():
        family = lock_refresh_token_family(session, presented.family_id)
        token = lock_refresh_token(session, presented.token_id, presented.digest)
        if family is None or token is None or token.family_id != family.id:
            raise InvalidCredentialsError()
        now = datetime.now(UTC)
        database_time = now.replace(tzinfo=None)
        user = find_user_by_id(session, family.user_id)
        if (
            user is None
            or user.status != "ACTIVE"
            or family.revoked_at is not None
            or family.absolute_expires_at <= database_time
            or token.revoked_at is not None
            or token.expires_at <= database_time
        ):
            raise InvalidCredentialsError()

        if token.rotated_at is not None:
            family.revoked_at = database_time
            family.revoke_reason = "ROTATED_TOKEN_REUSE"
            family.suspicious_reuse_at = database_time
            session.flush([family])
            reused = True
        else:
            successor_secret = generate_refresh_token()
            successor_expiry = min(
                now + REFRESH_TOKEN_LIFETIME,
                family.absolute_expires_at.replace(tzinfo=UTC),
            )
            successor = RefreshToken(
                family_id=family.id,
                token_hash=successor_secret.digest(),
                created_at=database_time,
                expires_at=successor_expiry.replace(tzinfo=None),
                revoked_at=None,
                last_used_at=None,
                rotated_at=None,
                replaced_by_id=None,
                generation=token.generation + 1,
            )
            token.last_used_at = database_time
            token.rotated_at = database_time
            rotate_refresh_token(session, token, successor)
            access_token = create_access_token(str(user.id), access_token_settings, now=now)
            issued = IssuedSession(
                access_token=access_token,
                refresh_token=successor_secret,
            )

    if reused:
        raise InvalidCredentialsError()
    if issued is None:
        raise RuntimeError("Refresh rotation completed without credentials")
    return issued


def logout_session(encoded_refresh_token: str | None, session: Session) -> None:
    if not encoded_refresh_token:
        return
    try:
        presented = _identify_refresh_token(encoded_refresh_token, session)
    except InvalidCredentialsError:
        return

    if session.in_transaction():
        raise RuntimeError("Logout requires a session without an active transaction")
    with session.begin():
        family = lock_refresh_token_family(session, presented.family_id)
        token = lock_refresh_token(session, presented.token_id, presented.digest)
        if family is None or token is None or token.family_id != family.id:
            return
        if family.revoked_at is None:
            family.revoked_at = datetime.now(UTC).replace(tzinfo=None)
            family.revoke_reason = "LOGOUT"
            session.flush([family])


def _identify_refresh_token(
    encoded_refresh_token: str,
    session: Session,
) -> _PresentedRefreshToken:
    try:
        opaque = parse_refresh_token(encoded_refresh_token)
    except RefreshTokenError as exc:
        raise InvalidCredentialsError() from exc
    token = find_refresh_token_by_digest(session, opaque.digest())
    if token is None:
        session.rollback()
        raise InvalidCredentialsError()
    presented = _PresentedRefreshToken(
        token_id=token.id,
        family_id=token.family_id,
        digest=opaque.digest(),
    )
    session.rollback()
    return presented


def current_user_response(user: User) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user.id,
        email=user.email_normalized,
        full_name=user.full_name,
        global_role=user.global_role,
        status="ACTIVE",
    )
