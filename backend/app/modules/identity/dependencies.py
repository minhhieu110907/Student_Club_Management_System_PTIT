from __future__ import annotations

import re
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationError
from app.core.security.jwt import AccessTokenError, decode_access_token
from app.db.session import get_db_session
from app.modules.identity.auth_config import AuthenticationSettings
from app.modules.identity.repository import find_user_by_id
from app.modules.identity.schemas import CurrentUserResponse
from app.modules.identity.service import current_user_response

_SIGNED_BIGINT_MAX = 2**63 - 1
_POSITIVE_INTEGER_PATTERN = re.compile(r"^[1-9][0-9]*$")
_bearer_scheme = HTTPBearer(auto_error=False)


def get_authentication_settings(request: Request) -> AuthenticationSettings:
    settings: AuthenticationSettings | None = request.app.state.authentication_settings
    if settings is None:
        raise RuntimeError("Authentication is not configured")
    return settings


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[AuthenticationSettings, Depends(get_authentication_settings)],
) -> CurrentUserResponse:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise AuthenticationError()
    try:
        claims = decode_access_token(credentials.credentials, settings.access_tokens)
        if len(claims.subject) > 19 or not _POSITIVE_INTEGER_PATTERN.fullmatch(claims.subject):
            raise AccessTokenError("Invalid access-token subject")
        user_id = int(claims.subject)
        if user_id > _SIGNED_BIGINT_MAX:
            raise AccessTokenError("Invalid access-token subject")
    except AccessTokenError as exc:
        raise AuthenticationError("Invalid authentication credentials") from exc

    user = find_user_by_id(session, user_id)
    if user is None or user.status != "ACTIVE":
        raise AuthenticationError("Invalid authentication credentials")
    return current_user_response(user)
