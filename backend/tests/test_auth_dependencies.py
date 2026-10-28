from datetime import UTC, datetime

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core.exceptions import AuthenticationError
from app.core.security.jwt import AccessTokenClaims, AccessTokenError, AccessTokenSettings
from app.modules.identity.auth_config import AuthenticationSettings
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User

SETTINGS = AuthenticationSettings(
    access_tokens=AccessTokenSettings(
        signing_key=b"k" * 32, issuer="scms-test", audience="scms-api"
    ),
    allowed_origins=frozenset({"https://scms.example"}),
    cookie_secure=True,
)
CREDENTIALS = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")


def _claims(subject: str) -> AccessTokenClaims:
    now = datetime.now(UTC)
    return AccessTokenClaims(
        subject=subject,
        token_id="token-id",
        issued_at=now,
        not_before=now,
        expires_at=now,
    )


def _user(status: str = "ACTIVE") -> User:
    return User(
        id=7,
        email_normalized="student@example.com",
        full_name="Student",
        password_hash="hidden",
        global_role="STUDENT",
        status=status,
    )


@pytest.mark.parametrize("subject", ["0", "-1", "01", "abc", str(2**63), "9" * 10_000])
def test_invalid_jwt_subject_is_rejected(subject: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.modules.identity.dependencies.decode_access_token", lambda *_: _claims(subject)
    )

    with pytest.raises(AuthenticationError):
        get_current_user(CREDENTIALS, object(), SETTINGS)


def test_active_current_user_returns_safe_dto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.modules.identity.dependencies.decode_access_token", lambda *_: _claims("7")
    )
    monkeypatch.setattr("app.modules.identity.dependencies.find_user_by_id", lambda *_: _user())

    current = get_current_user(CREDENTIALS, object(), SETTINGS)

    assert current.id == 7
    assert "password" not in current.model_dump()


@pytest.mark.parametrize("user", [None, _user("DISABLED")])
def test_missing_or_disabled_current_user_is_rejected(
    user: User | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.modules.identity.dependencies.decode_access_token", lambda *_: _claims("7")
    )
    monkeypatch.setattr("app.modules.identity.dependencies.find_user_by_id", lambda *_: user)

    with pytest.raises(AuthenticationError):
        get_current_user(CREDENTIALS, object(), SETTINGS)


def test_jwt_validation_error_is_mapped_to_authentication_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.identity.dependencies.decode_access_token",
        lambda *_: (_ for _ in ()).throw(AccessTokenError("invalid")),
    )

    with pytest.raises(AuthenticationError):
        get_current_user(CREDENTIALS, object(), SETTINGS)
