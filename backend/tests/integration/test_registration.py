from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.security.jwt import AccessTokenSettings
from app.core.security.tokens import parse_refresh_token
from app.db.session import DatabaseResources, create_session_factory
from app.main import create_app
from app.modules.identity import service as registration_service
from app.modules.identity.auth_config import AuthenticationSettings
from app.modules.identity.exceptions import EmailAlreadyRegisteredError, InvalidCredentialsError
from app.modules.identity.models import RefreshToken, RefreshTokenFamily, User
from app.modules.identity.schemas import LoginRequest, RegistrationRequest
from app.modules.identity.service import (
    login_user,
    logout_session,
    refresh_session,
    register_user,
)

DATABASE_URL = os.getenv("SCMS_REGISTRATION_INTEGRATION_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="SCMS_REGISTRATION_INTEGRATION_URL is required for registration verification",
    ),
]


@pytest.fixture
def engine() -> sa.Engine:
    assert DATABASE_URL is not None
    database_engine = sa.create_engine(DATABASE_URL, pool_pre_ping=True)
    with database_engine.begin() as connection:
        connection.execute(sa.delete(RefreshTokenFamily))
        connection.execute(sa.delete(User))
    try:
        yield database_engine
    finally:
        with database_engine.begin() as connection:
            connection.execute(sa.delete(RefreshTokenFamily))
            connection.execute(sa.delete(User))
        database_engine.dispose()


def _request(email: str = "Student@Example.com") -> RegistrationRequest:
    return RegistrationRequest(email=email, full_name="Student", password="abcdefghij")


class FakeReadinessService:
    def dispose(self) -> None:
        pass

    def is_ready(self) -> bool:
        return True


ACCESS_SETTINGS = AccessTokenSettings(
    signing_key=b"i" * 32,
    issuer="scms-integration",
    audience="scms-api",
)
AUTH_SETTINGS = AuthenticationSettings(
    access_tokens=ACCESS_SETTINGS,
    allowed_origins=frozenset({"http://testserver"}),
    cookie_secure=False,
)


def test_registration_persists_public_account_without_session_family(engine: sa.Engine) -> None:
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        response = register_user(_request(), session)

    with engine.connect() as connection:
        row = connection.execute(sa.select(User)).one()
        family_count = connection.scalar(sa.select(sa.func.count()).select_from(RefreshTokenFamily))

    assert response.id == row.id
    assert row.email_normalized == "student@example.com"
    assert row.full_name == "Student"
    assert row.global_role == "STUDENT"
    assert row.status == "ACTIVE"
    assert row.password_hash.startswith("$argon2id$")
    assert family_count == 0


def test_case_normalized_duplicate_is_rejected_by_unique_constraint(engine: sa.Engine) -> None:
    with Session(engine, autoflush=False, expire_on_commit=False) as first:
        register_user(_request("Student@Example.com"), first)

    with Session(engine, autoflush=False, expire_on_commit=False) as second:
        with pytest.raises(EmailAlreadyRegisteredError):
            register_user(_request("student@example.COM"), second)

    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(User)) == 1


def test_concurrent_duplicate_registration_has_one_winner(
    engine: sa.Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    insertion_barrier = threading.Barrier(2)
    real_add_user = registration_service.add_user

    def synchronized_add_user(session: Session, user: User) -> None:
        insertion_barrier.wait(timeout=10)
        real_add_user(session, user)

    monkeypatch.setattr(registration_service, "add_user", synchronized_add_user)

    def attempt(email: str) -> str:
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            try:
                registration_service.register_user(_request(email), session)
            except EmailAlreadyRegisteredError:
                return "duplicate"
            return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ("Concurrent@Example.com", "concurrent@example.COM")))

    assert sorted(results) == ["created", "duplicate"]
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(User)) == 1


def test_real_http_registration_uses_router_service_and_database(engine: sa.Engine) -> None:
    resources = DatabaseResources(engine=engine, session_factory=create_session_factory(engine))
    test_app = create_app(lambda: FakeReadinessService(), lambda: resources)

    with TestClient(test_app) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": " Http.Student@Example.COM ",
                "full_name": "  HTTP Student  ",
                "password": "abcdefghij",
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["email"] == "http.student@example.com"
    assert payload["full_name"] == "HTTP Student"
    assert payload["global_role"] == "STUDENT"
    assert payload["status"] == "ACTIVE"
    assert "password_hash" not in payload
    assert "token" not in response.text.lower()
    assert "Set-Cookie" not in response.headers

    with engine.connect() as connection:
        user = connection.execute(sa.select(User).where(User.id == payload["id"])).one()

    assert user.email_normalized == "http.student@example.com"
    assert user.global_role == "STUDENT"
    assert user.status == "ACTIVE"
    assert user.password_hash.startswith("$argon2id$")


def test_real_http_login_persists_initial_session_and_authenticates_me(
    engine: sa.Engine,
) -> None:
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        registered = register_user(_request("Login.Student@Example.com"), session)

    resources = DatabaseResources(engine=engine, session_factory=create_session_factory(engine))
    test_app = create_app(
        lambda: FakeReadinessService(),
        lambda: resources,
        lambda: AUTH_SETTINGS,
    )
    with TestClient(test_app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://testserver"},
            json={"email": "login.student@example.COM", "password": "abcdefghij"},
        )
        access_token = login_response.json()["access_token"]
        me_response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert login_response.status_code == 200
    assert login_response.json()["token_type"] == "bearer"
    assert login_response.json()["expires_in"] == 600
    assert "refresh" not in login_response.text.casefold()
    assert "HttpOnly" in login_response.headers["set-cookie"]
    assert "SameSite=lax" in login_response.headers["set-cookie"]
    assert "Path=/api/v1/auth" in login_response.headers["set-cookie"]
    raw_refresh_token = login_response.cookies["scms_refresh_token"]
    assert me_response.status_code == 200
    assert me_response.json()["id"] == registered.id
    assert "password" not in me_response.text

    with engine.connect() as connection:
        family = connection.execute(sa.select(RefreshTokenFamily)).one()
        token = connection.execute(sa.select(RefreshToken)).one()

    assert isinstance(family.id, bytes)
    assert len(family.id) == 16
    assert family.user_id == registered.id
    assert token.family_id == family.id
    assert token.generation == 0
    assert token.token_hash == parse_refresh_token(raw_refresh_token).digest()
    assert len(token.token_hash) == 32


def test_initial_token_failure_rolls_back_family(
    engine: sa.Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine, autoflush=False, expire_on_commit=False) as registration_session:
        register_user(_request("rollback@example.com"), registration_session)

    def fail_after_family(session, family, _token) -> None:
        session.add(family)
        session.flush()
        raise RuntimeError("initial token insert failed")

    monkeypatch.setattr(registration_service, "add_initial_session", fail_after_family)
    with Session(engine, autoflush=False, expire_on_commit=False) as login_session:
        with pytest.raises(RuntimeError, match="initial token insert failed"):
            login_user(
                LoginRequest(email="rollback@example.com", password="abcdefghij"),
                login_session,
                ACCESS_SETTINGS,
            )

    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(RefreshTokenFamily)) == 0
        assert connection.scalar(sa.select(sa.func.count()).select_from(RefreshToken)) == 0


def test_commit_failure_returns_no_credentials_and_rolls_back_session(engine: sa.Engine) -> None:
    with Session(engine, autoflush=False, expire_on_commit=False) as registration_session:
        register_user(_request("commit.failure@example.com"), registration_session)

    commit_error = RuntimeError("commit failed")
    with Session(engine, autoflush=False, expire_on_commit=False) as login_session:
        event.listen(
            login_session,
            "before_commit",
            lambda _session: (_ for _ in ()).throw(commit_error),
            once=True,
        )
        with pytest.raises(RuntimeError) as raised:
            login_user(
                LoginRequest(email="commit.failure@example.com", password="abcdefghij"),
                login_session,
                ACCESS_SETTINGS,
            )

    assert raised.value is commit_error
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(RefreshTokenFamily)) == 0
        assert connection.scalar(sa.select(sa.func.count()).select_from(RefreshToken)) == 0


def test_session_is_usable_after_duplicate_insert_rollback(engine: sa.Engine) -> None:
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        register_user(_request(), session)
        with pytest.raises(EmailAlreadyRegisteredError):
            register_user(_request("STUDENT@example.com"), session)
        second = register_user(_request("second@example.com"), session)

    assert second.email == "second@example.com"
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(User)) == 2


def test_registration_values_satisfy_real_mysql_constraints(engine: sa.Engine) -> None:
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        registered = register_user(_request("constraints@example.com"), session)

    with engine.connect() as connection:
        user = connection.execute(sa.select(User).where(User.id == registered.id)).one()

    assert user.created_at == user.updated_at
    assert len(user.email_normalized) <= 254
    assert len(user.password_hash) <= 255


def test_refresh_rotation_and_reuse_revokes_family(engine: sa.Engine) -> None:
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        register_user(_request("refresh.lifecycle@example.com"), session)

    resources = DatabaseResources(engine=engine, session_factory=create_session_factory(engine))
    test_app = create_app(
        lambda: FakeReadinessService(),
        lambda: resources,
        lambda: AUTH_SETTINGS,
    )
    with TestClient(test_app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://testserver"},
            json={"email": "refresh.lifecycle@example.com", "password": "abcdefghij"},
        )
        predecessor_raw = login_response.cookies["scms_refresh_token"]
        refresh_response = client.post(
            "/api/v1/auth/refresh",
            headers={"Origin": "http://testserver"},
        )
        successor_raw = refresh_response.cookies["scms_refresh_token"]
        reuse_response = client.post(
            "/api/v1/auth/refresh",
            headers={
                "Origin": "http://testserver",
                "Cookie": f"scms_refresh_token={predecessor_raw}",
            },
        )
        revoked_response = client.post(
            "/api/v1/auth/refresh",
            headers={
                "Origin": "http://testserver",
                "Cookie": f"scms_refresh_token={successor_raw}",
            },
        )

    assert login_response.status_code == 200
    assert refresh_response.status_code == 200
    assert successor_raw != predecessor_raw
    assert predecessor_raw not in refresh_response.text
    assert reuse_response.status_code == 401
    assert revoked_response.status_code == 401
    with engine.connect() as connection:
        family = connection.execute(sa.select(RefreshTokenFamily)).one()
        tokens = connection.execute(sa.select(RefreshToken).order_by(RefreshToken.generation)).all()
        current_count = connection.scalar(
            sa.select(sa.func.count())
            .select_from(RefreshToken)
            .where(RefreshToken.current_guard == 1)
        )

    assert family.revoked_at is not None
    assert family.revoke_reason == "ROTATED_TOKEN_REUSE"
    assert family.suspicious_reuse_at is not None
    assert len(tokens) == 2
    assert tokens[0].generation == 0
    assert tokens[0].rotated_at is not None
    assert tokens[0].replaced_by_id == tokens[1].id
    assert tokens[1].generation == 1
    assert tokens[1].token_hash == parse_refresh_token(successor_raw).digest()
    assert current_count == 1


def test_successor_insert_failure_rolls_back_rotation(
    engine: sa.Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        register_user(_request("refresh.rollback@example.com"), session)
        issued = login_user(
            LoginRequest(email="refresh.rollback@example.com", password="abcdefghij"),
            session,
            ACCESS_SETTINGS,
        )

    def fail_after_predecessor_flush(session, predecessor, _successor) -> None:
        session.flush([predecessor])
        raise RuntimeError("successor insert failed")

    monkeypatch.setattr(registration_service, "rotate_refresh_token", fail_after_predecessor_flush)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        with pytest.raises(RuntimeError, match="successor insert failed"):
            refresh_session(issued.refresh_token.reveal(), session, ACCESS_SETTINGS)

    with engine.connect() as connection:
        tokens = connection.execute(sa.select(RefreshToken)).all()
    assert len(tokens) == 1
    assert tokens[0].rotated_at is None
    assert tokens[0].replaced_by_id is None
    assert tokens[0].current_guard == 1


def test_concurrent_refreshes_serialize_and_trigger_strict_reuse(
    engine: sa.Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        register_user(_request("refresh.concurrent@example.com"), session)
        issued = login_user(
            LoginRequest(email="refresh.concurrent@example.com", password="abcdefghij"),
            session,
            ACCESS_SETTINGS,
        )

    family_lock_barrier = threading.Barrier(2)
    real_lock_family = registration_service.lock_refresh_token_family

    def synchronized_lock_family(session: Session, family_id: bytes):
        family_lock_barrier.wait(timeout=10)
        return real_lock_family(session, family_id)

    monkeypatch.setattr(
        registration_service,
        "lock_refresh_token_family",
        synchronized_lock_family,
    )

    def attempt() -> str:
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            try:
                refresh_session(issued.refresh_token.reveal(), session, ACCESS_SETTINGS)
            except InvalidCredentialsError:
                return "reused"
            return "rotated"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: attempt(), range(2)))

    assert sorted(results) == ["reused", "rotated"]
    with engine.connect() as connection:
        family = connection.execute(sa.select(RefreshTokenFamily)).one()
        token_count = connection.scalar(sa.select(sa.func.count()).select_from(RefreshToken))
        current_count = connection.scalar(
            sa.select(sa.func.count())
            .select_from(RefreshToken)
            .where(RefreshToken.current_guard == 1)
        )
    assert family.revoke_reason == "ROTATED_TOKEN_REUSE"
    assert token_count == 2
    assert current_count == 1


def test_logout_revokes_only_presented_family(engine: sa.Engine) -> None:
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        register_user(_request("logout.family@example.com"), session)
        first = login_user(
            LoginRequest(email="logout.family@example.com", password="abcdefghij"),
            session,
            ACCESS_SETTINGS,
        )
        second = login_user(
            LoginRequest(email="logout.family@example.com", password="abcdefghij"),
            session,
            ACCESS_SETTINGS,
        )

    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        logout_session(first.refresh_token.reveal(), session)
        logout_session(first.refresh_token.reveal(), session)

    first_digest = first.refresh_token.digest()
    second_digest = second.refresh_token.digest()
    with engine.connect() as connection:
        first_family = connection.execute(
            sa.select(RefreshTokenFamily.revoked_at, RefreshTokenFamily.revoke_reason)
            .join(RefreshToken, RefreshToken.family_id == RefreshTokenFamily.id)
            .where(RefreshToken.token_hash == first_digest)
        ).one()
        second_family = connection.execute(
            sa.select(RefreshTokenFamily.revoked_at, RefreshTokenFamily.revoke_reason)
            .join(RefreshToken, RefreshToken.family_id == RefreshTokenFamily.id)
            .where(RefreshToken.token_hash == second_digest)
        ).one()
    assert first_family.revoked_at is not None
    assert first_family.revoke_reason == "LOGOUT"
    assert second_family.revoked_at is None
