from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse

from app.core.exception_handlers import register_exception_handlers
from app.core.logging import JsonFormatter, configure_logging
from app.core.request_context import get_request_id, normalize_request_id
from app.main import RequestContextMiddleware, app


def test_json_formatter_emits_required_fields_and_context() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord("scms.test", logging.INFO, __file__, 1, "demo.event", (), None)
    record.request_id = "request-123"

    rendered = formatter.format(record)
    payload = json.loads(rendered)

    assert "\n" not in rendered
    assert payload["timestamp"].endswith("Z")
    assert payload["level"] == "INFO"
    assert payload["logger"] == "scms.test"
    assert payload["event"] == "demo.event"
    assert payload["request_id"] == "request-123"


def test_logging_configuration_does_not_duplicate_handlers() -> None:
    logger = configure_logging()
    initial_handlers = tuple(logger.handlers)

    configure_logging()

    assert tuple(logger.handlers) == initial_handlers


@pytest.mark.parametrize(
    "request_id",
    ["contains space", "bad/query", "x" * 129, ""],
)
def test_invalid_request_ids_are_replaced(request_id: str) -> None:
    response = TestClient(app).get("/api/v1/health", headers={"X-Request-ID": request_id})
    effective_id = response.headers["X-Request-ID"]

    assert response.status_code == 200
    assert effective_id != request_id
    assert re.fullmatch(r"[0-9a-f-]{36}", effective_id)


def test_non_ascii_request_id_is_replaced() -> None:
    effective_id = normalize_request_id("caf\N{LATIN SMALL LETTER E WITH ACUTE}")

    assert re.fullmatch(r"[0-9a-f-]{36}", effective_id)


def test_valid_request_id_is_returned_and_health_body_is_unchanged() -> None:
    response = TestClient(app).get(
        "/api/v1/health?access_token=not-for-logs",
        headers={"X-Request-ID": "client.trace-123:abc"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"] == "client.trace-123:abc"


def test_access_log_excludes_sensitive_request_values() -> None:
    client = TestClient(app)
    rendered_records: list[str] = []

    class CollectingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            rendered_records.append(self.format(record))

    handler = CollectingHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("scms")
    logger.addHandler(handler)
    try:
        client.get(
            "/api/v1/health?access_token=secret-query",
            headers={
                "Authorization": "Bearer secret-authorization",
                "Cookie": "refresh_token=secret-cookie",
                "X-Request-ID": "safe-request-id",
            },
        )
    finally:
        logger.removeHandler(handler)

    captured = rendered_records[-1]
    access_log = json.loads(captured)
    assert access_log["path"] == "/api/v1/health"
    assert access_log["status"] == 200
    assert access_log["request_id"] == "safe-request-id"
    assert "secret-query" not in captured
    assert "secret-authorization" not in captured
    assert "secret-cookie" not in captured


def test_concurrent_requests_keep_isolated_context() -> None:
    test_app = FastAPI()
    test_app.add_middleware(RequestContextMiddleware)
    both_started = asyncio.Event()
    started = 0

    @test_app.get("/context")
    async def context() -> dict[str, str | None]:
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        await asyncio.sleep(0)
        return {"request_id": get_request_id()}

    async def exercise() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await asyncio.gather(
                client.get("/context", headers={"X-Request-ID": "request-a"}),
                client.get("/context", headers={"X-Request-ID": "request-b"}),
            )

    responses = asyncio.run(exercise())

    assert [response.json()["request_id"] for response in responses] == [
        "request-a",
        "request-b",
    ]
    assert [response.headers["X-Request-ID"] for response in responses] == [
        "request-a",
        "request-b",
    ]
    assert get_request_id() is None


def test_exception_path_resets_context() -> None:
    test_app = FastAPI()
    test_app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(test_app)

    @test_app.get("/failure")
    async def failure() -> None:
        raise RuntimeError("expected test failure")

    with pytest.raises(RuntimeError, match="expected test failure"):
        TestClient(test_app).get("/failure", headers={"X-Request-ID": "failure-id"})

    assert get_request_id() is None


def test_unhandled_server_error_response_retains_request_id() -> None:
    test_app = FastAPI()
    test_app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(test_app)

    @test_app.get("/failure")
    async def failure() -> None:
        raise RuntimeError("expected test failure")

    response = TestClient(test_app, raise_server_exceptions=False).get(
        "/failure", headers={"X-Request-ID": "failure-response-id"}
    )

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "failure-response-id"


def test_exception_after_response_start_does_not_send_second_response() -> None:
    test_app = FastAPI()
    test_app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(test_app)

    @test_app.get("/stream-failure")
    async def stream_failure() -> StreamingResponse:
        async def content():
            yield b"started"
            raise RuntimeError("failure after response start")

        return StreamingResponse(content(), status_code=200)

    response = TestClient(test_app, raise_server_exceptions=False).get(
        "/stream-failure", headers={"X-Request-ID": "stream-failure-id"}
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "stream-failure-id"
