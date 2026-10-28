from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security.password import hash_password
from app.modules.identity.exceptions import EmailAlreadyRegisteredError
from app.modules.identity.models import User
from app.modules.identity.repository import add_user
from app.modules.identity.schemas import (
    RegisteredUserResponse,
    RegistrationRequest,
    normalize_email,
)

_MYSQL_DUPLICATE_KEY = 1062
_EMAIL_UNIQUE_CONSTRAINT = "uq_users_email_normalized"
_MYSQL_DUPLICATE_KEY_PATTERN = re.compile(r"\bfor key\s+['`]([^'`]+)['`]", re.IGNORECASE)


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
