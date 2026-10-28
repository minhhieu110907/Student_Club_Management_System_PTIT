from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import DatabaseResources, create_session_factory
from app.main import create_app
from app.modules.identity import service as registration_service
from app.modules.identity.exceptions import EmailAlreadyRegisteredError
from app.modules.identity.models import RefreshTokenFamily, User
from app.modules.identity.schemas import RegistrationRequest
from app.modules.identity.service import register_user

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
