import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.security.jwt import AccessTokenSettings, create_access_token
from app.core.security.tokens import OpaqueRefreshToken
from app.db.session import get_db_session
from app.main import create_app
from app.modules.identity import dependencies as auth_dependencies
from app.modules.identity import router as auth_router
from app.modules.identity.auth_config import AuthenticationSettings
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.exceptions import InvalidCredentialsError
from app.modules.identity.models import User
from app.modules.identity.schemas import CurrentUserResponse
from app.modules.identity.service import IssuedSession

ACCESS_SETTINGS = AccessTokenSettings(
    signing_key=b"k" * 32,
    issuer="scms-test",
    audience="scms-api",
)
AUTH_SETTINGS = AuthenticationSettings(
    access_tokens=ACCESS_SETTINGS,
    allowed_origins=frozenset({"https://scms.example"}),
    cookie_secure=True,
)


class FakeReadinessService:
    def dispose(self) -> None:
        pass

    def is_ready(self) -> bool:
        return True


def _app():
    test_app = create_app(
        lambda: FakeReadinessService(),
        lambda: None,
        lambda: AUTH_SETTINGS,
    )
    test_app.dependency_overrides[get_db_session] = lambda: object()
    return test_app


def _login_payload() -> dict[str, str]:
    return {"email": "student@example.com", "password": "user-password"}


def test_login_returns_access_token_and_secure_refresh_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opaque = OpaqueRefreshToken(b"r" * 32)
    monkeypatch.setattr(
        auth_router,
        "login_user",
        lambda *_: IssuedSession(access_token="signed-jwt", refresh_token=opaque),
    )

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://scms.example"},
            json=_login_payload(),
        )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "signed-jwt",
        "token_type": "bearer",
        "expires_in": 600,
    }
    assert opaque.reveal() not in response.text
    cookie = response.headers["set-cookie"]
    assert "scms_refresh_token=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert "Max-Age=604800" in cookie
    assert "Domain=" not in cookie


def test_login_rejects_unapproved_or_missing_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    login_service = pytest.fail
    monkeypatch.setattr(auth_router, "login_user", login_service)

    with TestClient(_app()) as client:
        unapproved = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://attacker.example"},
            json=_login_payload(),
        )
        missing = client.post("/api/v1/auth/login", json=_login_payload())

    assert unapproved.status_code == 403
    assert unapproved.json()["error_code"] == "ORIGIN_NOT_ALLOWED"
    assert missing.status_code == 403
    assert missing.json()["error_code"] == "ORIGIN_NOT_ALLOWED"


def test_login_rejects_malformed_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_router, "login_user", pytest.fail)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://[invalid-ipv6"},
            json=_login_payload(),
        )

    assert response.status_code == 403
    assert response.json()["error_code"] == "ORIGIN_NOT_ALLOWED"


def test_invalid_credentials_use_uniform_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_router,
        "login_user",
        lambda *_: (_ for _ in ()).throw(InvalidCredentialsError()),
    )

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://scms.example"},
            json=_login_payload(),
        )

    assert response.status_code == 401
    assert response.json()["error_code"] == "INVALID_CREDENTIALS"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert "Set-Cookie" not in response.headers


def test_me_returns_safe_current_user() -> None:
    test_app = _app()
    test_app.dependency_overrides[get_current_user] = lambda: CurrentUserResponse(
        id=7,
        email="student@example.com",
        full_name="Student",
        global_role="STUDENT",
        status="ACTIVE",
    )

    with TestClient(test_app) as client:
        response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": 7,
        "email": "student@example.com",
        "full_name": "Student",
        "global_role": "STUDENT",
        "status": "ACTIVE",
    }
    assert "password" not in response.text


def test_me_requires_bearer_token() -> None:
    with TestClient(_app()) as client:
        response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("kind", ["expired", "forged"])
def test_me_rejects_expired_or_forged_token(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    user = User(
        id=7,
        email_normalized="student@example.com",
        full_name="Student",
        password_hash="hidden",
        global_role="STUDENT",
        status="ACTIVE",
    )
    monkeypatch.setattr(auth_dependencies, "find_user_by_id", lambda *_: user)
    if kind == "expired":
        token = create_access_token(
            "7", ACCESS_SETTINGS, now=datetime.now(UTC) - timedelta(minutes=11)
        )
    else:
        forged_settings = AccessTokenSettings(
            signing_key=b"f" * 32,
            issuer="scms-test",
            audience="scms-api",
        )
        token = create_access_token("7", forged_settings)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_login_logs_and_response_do_not_expose_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sensitive-user-password"
    records: list[logging.LogRecord] = []

    class CollectingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    monkeypatch.setattr(
        auth_router,
        "login_user",
        lambda *_: (_ for _ in ()).throw(InvalidCredentialsError()),
    )
    logger = logging.getLogger("scms.access")
    handler = CollectingHandler()
    logger.addHandler(handler)
    try:
        with TestClient(_app()) as client:
            response = client.post(
                "/api/v1/auth/login",
                headers={"Origin": "https://scms.example"},
                json={"email": "student@example.com", "password": secret},
            )
    finally:
        logger.removeHandler(handler)

    assert secret not in response.text
    assert [record.getMessage() for record in records] == ["request.completed"]
    assert all(secret not in repr(record.__dict__) for record in records)


def test_refresh_returns_access_token_and_replaces_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = OpaqueRefreshToken(b"r" * 32)
    successor = OpaqueRefreshToken(b"s" * 32)
    monkeypatch.setattr(
        auth_router,
        "refresh_session",
        lambda raw, *_: IssuedSession(
            access_token="refreshed-jwt",
            refresh_token=successor,
        )
        if raw == current.reveal()
        else pytest.fail("unexpected refresh credential"),
    )

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/auth/refresh",
            headers={
                "Origin": "https://scms.example",
                "Cookie": f"scms_refresh_token={current.reveal()}",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "refreshed-jwt",
        "token_type": "bearer",
        "expires_in": 600,
    }
    assert current.reveal() not in response.text
    cookie = response.headers["set-cookie"]
    assert successor.reveal() in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie
    assert "Path=/api/v1/auth" in cookie


def test_refresh_rejects_missing_cookie_and_wrong_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_router, "refresh_session", pytest.fail)

    with TestClient(_app()) as client:
        missing = client.post(
            "/api/v1/auth/refresh",
            headers={"Origin": "https://scms.example"},
        )
        wrong_origin = client.post(
            "/api/v1/auth/refresh",
            headers={
                "Origin": "https://attacker.example",
                "Cookie": "scms_refresh_token=not-used",
            },
        )

    assert missing.status_code == 401
    assert missing.json()["error_code"] == "INVALID_CREDENTIALS"
    assert wrong_origin.status_code == 403
    assert wrong_origin.json()["error_code"] == "ORIGIN_NOT_ALLOWED"


def test_logout_is_idempotent_and_clears_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = OpaqueRefreshToken(b"r" * 32).reveal()
    presented: list[str | None] = []
    monkeypatch.setattr(
        auth_router,
        "logout_session",
        lambda token, _session: presented.append(token),
    )

    with TestClient(_app()) as client:
        first = client.post(
            "/api/v1/auth/logout",
            headers={
                "Origin": "https://scms.example",
                "Cookie": f"scms_refresh_token={raw}",
            },
        )
        second = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://scms.example"},
        )

    assert first.status_code == 204
    assert second.status_code == 204
    assert presented == [raw, None]
    cookie = first.headers["set-cookie"]
    assert "scms_refresh_token=" in cookie
    assert "Max-Age=0" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie
    assert "Path=/api/v1/auth" in cookie


def test_logout_does_not_swallow_database_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_router,
        "logout_session",
        MagicMock(side_effect=RuntimeError("database unavailable")),
    )

    with TestClient(_app()) as client, pytest.raises(RuntimeError, match="database unavailable"):
        client.post(
            "/api/v1/auth/logout",
            headers={
                "Origin": "https://scms.example",
                "Cookie": f"scms_refresh_token={OpaqueRefreshToken(b'r' * 32).reveal()}",
            },
        )
