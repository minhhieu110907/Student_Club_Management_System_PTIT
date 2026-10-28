from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.modules.identity.auth_config import (
    REFRESH_COOKIE_MAX_AGE_SECONDS,
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
    AuthenticationSettings,
    normalize_request_origin,
)
from app.modules.identity.dependencies import (
    get_authentication_settings,
    get_current_user,
)
from app.modules.identity.exceptions import OriginNotAllowedError
from app.modules.identity.schemas import (
    CurrentUserResponse,
    LoginRequest,
    LoginResponse,
    RegisteredUserResponse,
    RegistrationRequest,
)
from app.modules.identity.service import login_user, register_user

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.post(
    "/register",
    response_model=RegisteredUserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    request: RegistrationRequest,
    session: Annotated[Session, Depends(get_db_session)],
) -> RegisteredUserResponse:
    return register_user(request, session)


@router.post("/login", response_model=LoginResponse)
def login(
    request_body: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[AuthenticationSettings, Depends(get_authentication_settings)],
) -> LoginResponse:
    origin = request.headers.get("origin")
    try:
        normalized_origin = normalize_request_origin(origin or "")
    except ValueError as exc:
        raise OriginNotAllowedError() from exc
    if normalized_origin not in settings.allowed_origins:
        raise OriginNotAllowedError()

    issued = login_user(request_body, session, settings.access_tokens)
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=issued.refresh_token.reveal(),
        max_age=REFRESH_COOKIE_MAX_AGE_SECONDS,
        path=REFRESH_COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return LoginResponse(access_token=issued.access_token)


@router.get("/me", response_model=CurrentUserResponse)
def me(
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> CurrentUserResponse:
    return current_user
