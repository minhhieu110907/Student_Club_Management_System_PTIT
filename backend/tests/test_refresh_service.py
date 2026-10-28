from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.core.security.jwt import AccessTokenSettings
from app.core.security.tokens import OpaqueRefreshToken
from app.modules.identity.exceptions import InvalidCredentialsError
from app.modules.identity.models import RefreshToken, RefreshTokenFamily, User
from app.modules.identity.service import logout_session, refresh_session

SETTINGS = AccessTokenSettings(
    signing_key=b"k" * 32,
    issuer="scms-test",
    audience="scms-api",
)
RAW = OpaqueRefreshToken(b"r" * 32)
SUCCESSOR = OpaqueRefreshToken(b"s" * 32)


def _family(*, revoked: bool = False) -> RefreshTokenFamily:
    now = datetime.now(UTC).replace(tzinfo=None)
    return RefreshTokenFamily(
        id=b"f" * 16,
        user_id=7,
        created_at=now - timedelta(days=1),
        absolute_expires_at=now + timedelta(days=20),
        revoked_at=now if revoked else None,
        revoke_reason="LOGOUT" if revoked else None,
        suspicious_reuse_at=None,
        purge_after=now + timedelta(days=50),
    )


def _token(*, rotated: bool = False, expired: bool = False) -> RefreshToken:
    now = datetime.now(UTC).replace(tzinfo=None)
    return RefreshToken(
        id=11,
        family_id=b"f" * 16,
        token_hash=RAW.digest(),
        created_at=now - timedelta(days=1),
        expires_at=now - timedelta(seconds=1) if expired else now + timedelta(days=6),
        revoked_at=None,
        last_used_at=None,
        rotated_at=now if rotated else None,
        replaced_by_id=12 if rotated else None,
        generation=0,
    )


def _user(*, status: str = "ACTIVE") -> User:
    return User(id=7, status=status)


def _session() -> MagicMock:
    session = MagicMock()
    session.in_transaction.return_value = False
    session.begin.return_value = nullcontext()
    return session


def _arrange_lookup(
    monkeypatch: pytest.MonkeyPatch,
    family: RefreshTokenFamily,
    token: RefreshToken,
    user: User | None = None,
) -> MagicMock:
    session = _session()
    monkeypatch.setattr(
        "app.modules.identity.service.find_refresh_token_by_digest", lambda *_: token
    )
    monkeypatch.setattr("app.modules.identity.service.lock_refresh_token_family", lambda *_: family)
    monkeypatch.setattr("app.modules.identity.service.lock_refresh_token", lambda *_: token)
    monkeypatch.setattr("app.modules.identity.service.find_user_by_id", lambda *_: user or _user())
    return session


def test_valid_refresh_rotates_and_issues_successor(monkeypatch: pytest.MonkeyPatch) -> None:
    family = _family()
    token = _token()
    session = _arrange_lookup(monkeypatch, family, token)
    captured = {}
    monkeypatch.setattr("app.modules.identity.service.generate_refresh_token", lambda: SUCCESSOR)
    monkeypatch.setattr("app.modules.identity.service.create_access_token", lambda *_a, **_k: "jwt")

    def capture(_session, predecessor, successor) -> None:
        captured["predecessor"] = predecessor
        captured["successor"] = successor

    monkeypatch.setattr("app.modules.identity.service.rotate_refresh_token", capture)

    issued = refresh_session(RAW.reveal(), session, SETTINGS)

    assert issued.access_token == "jwt"
    assert issued.refresh_token is SUCCESSOR
    assert token.rotated_at is not None
    assert captured["predecessor"] is token
    successor = captured["successor"]
    assert successor.generation == 1
    assert successor.token_hash == SUCCESSOR.digest()
    assert successor.expires_at <= family.absolute_expires_at


def test_rotated_token_reuse_commits_family_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    family = _family()
    session = _arrange_lookup(monkeypatch, family, _token(rotated=True))

    with pytest.raises(InvalidCredentialsError):
        refresh_session(RAW.reveal(), session, SETTINGS)

    assert family.revoked_at is not None
    assert family.suspicious_reuse_at == family.revoked_at
    assert family.revoke_reason == "ROTATED_TOKEN_REUSE"
    session.flush.assert_called_once_with([family])


@pytest.mark.parametrize(
    ("family", "token", "user"),
    [
        (_family(revoked=True), _token(), _user()),
        (_family(), _token(expired=True), _user()),
        (_family(), _token(), _user(status="DISABLED")),
    ],
)
def test_invalid_refresh_state_uses_uniform_credentials_error(
    family: RefreshTokenFamily,
    token: RefreshToken,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _arrange_lookup(monkeypatch, family, token, user)

    with pytest.raises(InvalidCredentialsError):
        refresh_session(RAW.reveal(), session, SETTINGS)


def test_unknown_and_malformed_refresh_tokens_fail_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    monkeypatch.setattr(
        "app.modules.identity.service.find_refresh_token_by_digest", lambda *_: None
    )

    with pytest.raises(InvalidCredentialsError):
        refresh_session(RAW.reveal(), session, SETTINGS)
    with pytest.raises(InvalidCredentialsError):
        refresh_session("malformed", session, SETTINGS)


def test_logout_revokes_known_family_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    family = _family()
    session = _arrange_lookup(monkeypatch, family, _token())

    logout_session(RAW.reveal(), session)
    first_revoked_at = family.revoked_at
    logout_session(RAW.reveal(), session)

    assert first_revoked_at is not None
    assert family.revoked_at == first_revoked_at
    assert family.revoke_reason == "LOGOUT"


def test_logout_missing_or_unknown_token_is_successful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    monkeypatch.setattr(
        "app.modules.identity.service.find_refresh_token_by_digest", lambda *_: None
    )

    logout_session(None, session)
    logout_session(RAW.reveal(), session)


def test_logout_does_not_swallow_database_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    database_error = RuntimeError("database unavailable")
    monkeypatch.setattr(
        "app.modules.identity.service.find_refresh_token_by_digest",
        MagicMock(side_effect=database_error),
    )

    with pytest.raises(RuntimeError) as caught:
        logout_session(RAW.reveal(), session)

    assert caught.value is database_error
