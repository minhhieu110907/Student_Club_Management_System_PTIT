from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.core.security.jwt import AccessTokenSettings, SecurityConfigurationError

REFRESH_COOKIE_NAME = "scms_refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"
REFRESH_COOKIE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class AuthenticationSettings:
    access_tokens: AccessTokenSettings
    allowed_origins: frozenset[str]
    cookie_secure: bool


def build_authentication_settings(
    environment: Mapping[str, str] | None = None,
) -> AuthenticationSettings | None:
    values = os.environ if environment is None else environment
    auth_keys = (
        "SCMS_JWT_SECRET",
        "SCMS_JWT_ISSUER",
        "SCMS_JWT_AUDIENCE",
        "SCMS_AUTH_ALLOWED_ORIGINS",
        "SCMS_COOKIE_SECURE",
    )
    environment_name = values.get("SCMS_ENV", "development").strip().casefold()
    if not any(values.get(key, "").strip() for key in auth_keys):
        if environment_name == "production":
            raise SecurityConfigurationError("Authentication must be configured in production")
        return None

    access_tokens = AccessTokenSettings.from_environment(values)
    configured_origins = values.get("SCMS_AUTH_ALLOWED_ORIGINS", "")
    allowed_origins = frozenset(
        _normalize_origin(origin.strip())
        for origin in configured_origins.split(",")
        if origin.strip()
    )
    if not allowed_origins:
        raise SecurityConfigurationError("SCMS_AUTH_ALLOWED_ORIGINS must not be empty")

    raw_cookie_secure = values.get("SCMS_COOKIE_SECURE", "").strip().casefold()
    if raw_cookie_secure:
        if raw_cookie_secure not in {"true", "false"}:
            raise SecurityConfigurationError("SCMS_COOKIE_SECURE must be true or false")
        cookie_secure = raw_cookie_secure == "true"
    else:
        cookie_secure = environment_name == "production"
    if environment_name == "production" and not cookie_secure:
        raise SecurityConfigurationError("Production refresh cookies must be Secure")

    return AuthenticationSettings(
        access_tokens=access_tokens,
        allowed_origins=allowed_origins,
        cookie_secure=cookie_secure,
    )


def normalize_request_origin(value: str) -> str:
    try:
        return _normalize_origin(value)
    except SecurityConfigurationError as exc:
        raise ValueError("Invalid Origin header") from exc


def _normalize_origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise SecurityConfigurationError("Allowed origins must be HTTP(S) origins") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise SecurityConfigurationError("Allowed origins must be HTTP(S) origins")
    return f"{parsed.scheme.casefold()}://{parsed.netloc.casefold()}"
