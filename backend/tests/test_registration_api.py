import logging
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app
from app.modules.identity import router as registration_router
from app.modules.identity.exceptions import EmailAlreadyRegisteredError
from app.modules.identity.schemas import RegisteredUserResponse


class FakeReadinessService:
    def dispose(self) -> None:
        pass

    def is_ready(self) -> bool:
        return True


def _app(handler, monkeypatch: pytest.MonkeyPatch):
    test_app = create_app(lambda: FakeReadinessService(), lambda: None)
    test_app.dependency_overrides[get_db_session] = lambda: object()
    monkeypatch.setattr(registration_router, "register_user", handler)
    return test_app


def _success(_request, _session) -> RegisteredUserResponse:
    return RegisteredUserResponse(
        id=42,
        email="student@example.com",
        full_name="Student",
        global_role="STUDENT",
        status="ACTIVE",
        created_at=datetime(2026, 10, 28, tzinfo=UTC),
    )


def test_registration_returns_201_without_authentication_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(_app(_success, monkeypatch)) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "Student@Example.com",
                "full_name": "Student",
                "password": "abcdefghij",
            },
        )

    assert response.status_code == 201
    assert response.json() == {
        "id": 42,
        "email": "student@example.com",
        "full_name": "Student",
        "global_role": "STUDENT",
        "status": "ACTIVE",
        "created_at": "2026-10-28T00:00:00Z",
    }
    assert "Set-Cookie" not in response.headers
    assert "token" not in response.text.lower()


def test_duplicate_email_uses_standard_error_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    def duplicate(_request, _session):
        raise EmailAlreadyRegisteredError

    with TestClient(_app(duplicate, monkeypatch)) as client:
        response = client.post(
            "/api/v1/auth/register",
            headers={"X-Request-ID": "registration-request-id"},
            json={
                "email": "student@example.com",
                "full_name": "Student",
                "password": "abcdefghij",
            },
        )

    assert response.status_code == 409
    assert response.json() == {
        "success": False,
        "message": "Email is already registered",
        "error_code": "EMAIL_ALREADY_REGISTERED",
        "details": None,
        "request_id": "registration-request-id",
    }


def test_invalid_body_and_role_escalation_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(_app(_success, monkeypatch)) as client:
        invalid = client.post(
            "/api/v1/auth/register",
            json={"email": "invalid", "full_name": "", "password": "short"},
        )
        escalation = client.post(
            "/api/v1/auth/register",
            json={
                "email": "student@example.com",
                "full_name": "Student",
                "password": "abcdefghij",
                "global_role": "ADMIN",
                "status": "ACTIVE",
            },
        )

    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "VALIDATION_ERROR"
    assert escalation.status_code == 422
    locations = [detail["location"] for detail in escalation.json()["details"]]
    assert ["body", "global_role"] in locations
    assert ["body", "status"] in locations


def test_validation_response_and_logs_do_not_expose_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "secret-password-value"
    records: list[logging.LogRecord] = []

    class CollectingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("scms.access")
    handler = CollectingHandler()
    logger.addHandler(handler)
    try:
        with TestClient(_app(_success, monkeypatch)) as client:
            response = client.post(
                "/api/v1/auth/register",
                json={"email": "invalid", "full_name": "Student", "password": secret},
            )
    finally:
        logger.removeHandler(handler)

    assert secret not in response.text
    assert [record.getMessage() for record in records] == ["request.completed"]
    assert all(secret not in repr(record.__dict__) for record in records)
