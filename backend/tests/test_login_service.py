from contextlib import nullcontext
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from app.core.security.jwt import AccessTokenSettings
from app.core.security.tokens import OpaqueRefreshToken
from app.modules.identity.exceptions import InvalidCredentialsError
from app.modules.identity.models import User
from app.modules.identity.schemas import LoginRequest
from app.modules.identity.service import (
    FAMILY_ABSOLUTE_LIFETIME,
    FAMILY_RETENTION,
    REFRESH_TOKEN_LIFETIME,
    login_user,
)

TOKEN_SETTINGS = AccessTokenSettings(
    signing_key=b"k" * 32,
    issuer="scms-test",
    audience="scms-api",
)


def _request() -> LoginRequest:
    return LoginRequest(email="Student@Example.com", password="abcdefghij")


def _user(*, status: str = "ACTIVE") -> User:
    return User(
        id=7,
        email_normalized="student@example.com",
        full_name="Student",
        password_hash="encoded-hash",
        global_role="STUDENT",
        status=status,
    )


def test_valid_login_issues_atomic_initial_session(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    session.in_transaction.return_value = False
    session.begin.return_value = nullcontext()
    user = _user()
    captured = {}
    opaque = OpaqueRefreshToken(b"r" * 32)
    monkeypatch.setattr("app.modules.identity.service.find_user_by_email", lambda *_: user)
    monkeypatch.setattr("app.modules.identity.service.find_user_by_id", lambda *_: user)
    monkeypatch.setattr("app.modules.identity.service.verify_password", lambda *_: True)
    monkeypatch.setattr("app.modules.identity.service.create_access_token", lambda *_a, **_k: "jwt")
    monkeypatch.setattr("app.modules.identity.service.generate_refresh_token", lambda: opaque)

    def capture(_session, family, token) -> None:
        captured["family"] = family
        captured["token"] = token

    monkeypatch.setattr("app.modules.identity.service.add_initial_session", capture)

    issued = login_user(_request(), session, TOKEN_SETTINGS)

    family = captured["family"]
    token = captured["token"]
    assert issued.access_token == "jwt"
    assert issued.refresh_token is opaque
    assert len(family.id) == 16
    assert family.user_id == 7
    assert family.absolute_expires_at - family.created_at == FAMILY_ABSOLUTE_LIFETIME
    assert family.purge_after - family.absolute_expires_at == FAMILY_RETENTION
    assert token.family_id == family.id
    assert token.generation == 0
    assert token.token_hash == opaque.digest()
    assert token.expires_at - token.created_at == REFRESH_TOKEN_LIFETIME
    session.rollback.assert_called_once_with()
    session.begin.assert_called_once_with()


@pytest.mark.parametrize("user", [None, _user(status="DISABLED")])
def test_missing_or_disabled_user_has_uniform_invalid_credentials(
    user: User | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = MagicMock()
    monkeypatch.setattr("app.modules.identity.service.find_user_by_email", lambda *_: user)
    monkeypatch.setattr("app.modules.identity.service.verify_password", lambda *_: True)

    with pytest.raises(InvalidCredentialsError):
        login_user(_request(), session, TOKEN_SETTINGS)


def test_incorrect_password_does_not_open_issuance_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    monkeypatch.setattr("app.modules.identity.service.find_user_by_email", lambda *_: _user())
    monkeypatch.setattr("app.modules.identity.service.verify_password", lambda *_: False)

    with pytest.raises(InvalidCredentialsError):
        login_user(_request(), session, TOKEN_SETTINGS)

    session.begin.assert_not_called()


def test_database_error_is_not_converted_to_invalid_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    database_error = RuntimeError("database unavailable")
    monkeypatch.setattr(
        "app.modules.identity.service.find_user_by_email",
        MagicMock(side_effect=database_error),
    )

    with pytest.raises(RuntimeError) as caught:
        login_user(_request(), session, TOKEN_SETTINGS)

    assert caught.value is database_error
    session.begin.assert_not_called()


def test_jwt_issuance_failure_does_not_open_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    monkeypatch.setattr("app.modules.identity.service.find_user_by_email", lambda *_: _user())
    monkeypatch.setattr("app.modules.identity.service.verify_password", lambda *_: True)
    monkeypatch.setattr(
        "app.modules.identity.service.create_access_token",
        MagicMock(side_effect=RuntimeError("jwt failure")),
    )

    with pytest.raises(RuntimeError, match="jwt failure"):
        login_user(_request(), session, TOKEN_SETTINGS)

    session.begin.assert_not_called()


def test_fresh_disabled_status_rolls_back_issuance(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    session.in_transaction.return_value = False
    session.begin.return_value = nullcontext()
    monkeypatch.setattr("app.modules.identity.service.find_user_by_email", lambda *_: _user())
    monkeypatch.setattr(
        "app.modules.identity.service.find_user_by_id", lambda *_: _user(status="DISABLED")
    )
    monkeypatch.setattr("app.modules.identity.service.verify_password", lambda *_: True)
    monkeypatch.setattr("app.modules.identity.service.create_access_token", lambda *_a, **_k: "jwt")

    with pytest.raises(InvalidCredentialsError):
        login_user(_request(), session, TOKEN_SETTINGS)


def test_session_lifetimes_are_exact_v1_values() -> None:
    assert REFRESH_TOKEN_LIFETIME == timedelta(days=7)
    assert FAMILY_ABSOLUTE_LIFETIME == timedelta(days=30)
    assert FAMILY_RETENTION == timedelta(days=30)
