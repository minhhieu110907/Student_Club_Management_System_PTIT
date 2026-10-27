from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.exception_handlers import register_exception_handlers
from app.core.exceptions import (
    AuthenticationError,
    BadRequestException,
    ConflictException,
    ForbiddenError,
    NotFoundException,
)
from app.core.request_context import get_request_id
from app.main import RequestContextMiddleware, app


def _test_app(*, debug: bool = False) -> FastAPI:
    test_app = FastAPI(debug=debug)
    test_app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(test_app)
    return test_app


def _assert_contract(response, *, status: int, code: str, message: str) -> None:
    assert response.status_code == status
    payload = response.json()
    assert payload == {
        "success": False,
        "message": message,
        "error_code": code,
        "details": None,
        "request_id": "test-request-id",
    }
    assert response.headers["X-Request-ID"] == payload["request_id"]


@pytest.mark.parametrize(
    ("path", "exception", "status", "code", "message"),
    [
        ("/bad", BadRequestException("Invalid operation"), 400, "BAD_REQUEST", "Invalid operation"),
        ("/auth", AuthenticationError(), 401, "UNAUTHORIZED", "Authentication required"),
        ("/forbidden", ForbiddenError(), 403, "FORBIDDEN", "Forbidden"),
        ("/missing", NotFoundException(), 404, "NOT_FOUND", "Resource not found"),
        ("/conflict", ConflictException(), 409, "CONFLICT", "Conflict"),
    ],
)
def test_app_exceptions_use_standard_contract(
    path: str, exception: Exception, status: int, code: str, message: str
) -> None:
    test_app = _test_app()

    @test_app.get(path)
    async def failure() -> None:
        raise exception

    response = TestClient(test_app).get(path, headers={"X-Request-ID": "test-request-id"})

    _assert_contract(response, status=status, code=code, message=message)
    if status == 401:
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_unknown_route_uses_standard_404_contract() -> None:
    response = TestClient(app).get("/does-not-exist", headers={"X-Request-ID": "test-request-id"})

    _assert_contract(response, status=404, code="NOT_FOUND", message="Not Found")


def test_http_exception_preserves_safe_headers() -> None:
    test_app = _test_app()

    @test_app.get("/limited")
    async def limited() -> None:
        raise HTTPException(
            status_code=429, detail="Try again later", headers={"Retry-After": "30"}
        )

    response = TestClient(test_app).get("/limited", headers={"X-Request-ID": "test-request-id"})

    _assert_contract(response, status=429, code="TOO_MANY_REQUESTS", message="Try again later")
    assert response.headers["Retry-After"] == "30"


def test_method_not_allowed_preserves_allow_header() -> None:
    test_app = _test_app()

    @test_app.get("/read-only")
    async def read_only() -> None:
        return None

    response = TestClient(test_app).post("/read-only", headers={"X-Request-ID": "test-request-id"})

    _assert_contract(response, status=405, code="METHOD_NOT_ALLOWED", message="Method Not Allowed")
    assert response.headers["Allow"] == "GET"


def test_unapproved_exception_headers_are_not_forwarded() -> None:
    test_app = _test_app()

    @test_app.get("/unsafe-headers")
    async def unsafe_headers() -> None:
        raise HTTPException(
            status_code=400,
            detail="Bad request",
            headers={
                "Set-Cookie": "session=unsafe",
                "X-Internal-Debug": "private-value",
                "X-Request-ID": "exception-controlled-id",
                "wWw-AuThEnTiCaTe": "Bearer safe",
            },
        )

    response = TestClient(test_app).get(
        "/unsafe-headers", headers={"X-Request-ID": "test-request-id"}
    )

    _assert_contract(response, status=400, code="BAD_REQUEST", message="Bad request")
    assert response.headers["WWW-Authenticate"] == "Bearer safe"
    assert "Set-Cookie" not in response.headers
    assert "X-Internal-Debug" not in response.headers
    assert response.headers["X-Request-ID"] == "test-request-id"


def test_validation_error_is_sanitized() -> None:
    test_app = _test_app()

    @test_app.get("/validate")
    async def validate(count: int) -> dict[str, int]:
        return {"count": count}

    response = TestClient(test_app).get(
        "/validate?count=secret-invalid-value",
        headers={"X-Request-ID": "test-request-id"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error_code"] == "VALIDATION_ERROR"
    assert payload["message"] == "Request validation failed"
    assert payload["request_id"] == response.headers["X-Request-ID"]
    assert payload["details"] == [{"location": ["query", "count"], "type": "int_parsing"}]
    assert "secret-invalid-value" not in response.text


def test_unexpected_error_is_sanitized_and_exception_is_preserved() -> None:
    test_app = _test_app()

    @test_app.get("/failure")
    async def failure() -> None:
        raise RuntimeError("database password=secret-value")

    client = TestClient(test_app, raise_server_exceptions=False)
    response = client.get("/failure", headers={"X-Request-ID": "test-request-id"})

    _assert_contract(
        response,
        status=500,
        code="INTERNAL_SERVER_ERROR",
        message="Internal server error",
    )
    assert "secret-value" not in response.text

    with pytest.raises(RuntimeError, match="database password=secret-value"):
        TestClient(test_app).get("/failure", headers={"X-Request-ID": "test-request-id"})
    assert get_request_id() is None


def test_unexpected_error_has_one_application_access_log() -> None:
    test_app = _test_app()
    records: list[logging.LogRecord] = []

    class CollectingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    @test_app.get("/failure")
    async def failure() -> None:
        raise RuntimeError("internal failure")

    handler = CollectingHandler()
    logger = logging.getLogger("scms")
    logger.addHandler(handler)
    try:
        TestClient(test_app, raise_server_exceptions=False).get("/failure")
    finally:
        logger.removeHandler(handler)

    assert [record.getMessage() for record in records] == ["request.completed"]


def test_debug_mode_uses_starlette_traceback_response() -> None:
    test_app = _test_app(debug=True)

    @test_app.get("/failure")
    async def failure() -> None:
        raise RuntimeError("debug traceback marker")

    response = TestClient(test_app, raise_server_exceptions=False).get("/failure")

    assert response.status_code == 500
    assert "debug traceback marker" in response.text
    assert response.headers.get("X-Request-ID") is None


def test_health_response_remains_unchanged() -> None:
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
