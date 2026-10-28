import base64

import pytest

from app.core.security.jwt import SecurityConfigurationError
from app.modules.identity.auth_config import (
    build_authentication_settings,
    normalize_request_origin,
)


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        "SCMS_JWT_SECRET": base64.urlsafe_b64encode(b"s" * 32).rstrip(b"=").decode(),
        "SCMS_JWT_ISSUER": "scms-test",
        "SCMS_JWT_AUDIENCE": "scms-api",
        "SCMS_AUTH_ALLOWED_ORIGINS": "http://localhost:8080,https://scms.example",
        "SCMS_COOKIE_SECURE": "true",
        "SCMS_ENV": "test",
    }
    values.update(overrides)
    return values


def test_authentication_configuration_is_optional_outside_production() -> None:
    assert build_authentication_settings({}) is None


def test_authentication_configuration_parses_origins_and_cookie_policy() -> None:
    settings = build_authentication_settings(_environment())

    assert settings is not None
    assert settings.allowed_origins == {
        "http://localhost:8080",
        "https://scms.example",
    }
    assert settings.cookie_secure is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"SCMS_ENV": "production", "SCMS_COOKIE_SECURE": "false"},
        {"SCMS_AUTH_ALLOWED_ORIGINS": ""},
        {"SCMS_AUTH_ALLOWED_ORIGINS": "https://example.com/path"},
        {"SCMS_AUTH_ALLOWED_ORIGINS": "https://[invalid-ipv6"},
        {"SCMS_COOKIE_SECURE": "sometimes"},
    ],
)
def test_unsafe_authentication_configuration_is_rejected(overrides: dict[str, str]) -> None:
    with pytest.raises(SecurityConfigurationError):
        build_authentication_settings(_environment(**overrides))


def test_production_without_authentication_configuration_fails_closed() -> None:
    with pytest.raises(SecurityConfigurationError):
        build_authentication_settings({"SCMS_ENV": "production"})


@pytest.mark.parametrize("origin", ["https://[invalid-ipv6", "https://invalid-ipv6]"])
def test_malformed_request_origin_is_rejected(origin: str) -> None:
    with pytest.raises(ValueError, match="Invalid Origin header"):
        normalize_request_origin(origin)
