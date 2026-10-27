from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.health.service import build_readiness_service
from app.main import create_app

READY_URL = os.getenv("SCMS_READINESS_READY_URL")
EMPTY_URL = os.getenv("SCMS_READINESS_EMPTY_URL")
WRONG_URL = os.getenv("SCMS_READINESS_WRONG_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not all((READY_URL, EMPTY_URL, WRONG_URL)),
        reason="isolated readiness integration database URLs are not configured",
    ),
]


def _request(monkeypatch: pytest.MonkeyPatch, database_url: str | None):
    if database_url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", database_url)
    test_app = create_app(build_readiness_service)
    with TestClient(test_app) as client:
        return client.get(
            "/api/v1/health/ready",
            headers={"X-Request-ID": "readiness-integration-id"},
        )


def _assert_not_ready(response) -> None:
    assert response.status_code == 503
    assert response.headers["X-Request-ID"] == "readiness-integration-id"
    assert response.json() == {
        "success": False,
        "message": "Service is not ready",
        "error_code": "NOT_READY",
        "details": None,
        "request_id": "readiness-integration-id",
    }
    assert "mysql" not in response.text.lower()
    assert "password" not in response.text.lower()


def test_migrated_database_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _request(monkeypatch, READY_URL)

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert response.headers["X-Request-ID"] == "readiness-integration-id"


def test_empty_database_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_not_ready(_request(monkeypatch, EMPTY_URL))


def test_wrong_revision_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_not_ready(_request(monkeypatch, WRONG_URL))


def test_missing_database_url_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_not_ready(_request(monkeypatch, None))
