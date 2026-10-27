from __future__ import annotations

import logging
from time import perf_counter

from fastapi import FastAPI
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.exception_handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.core.request_context import (
    REQUEST_ID_HEADER,
    normalize_request_id,
    reset_request_id,
    set_request_id,
)


class RequestContextMiddleware:
    """Correlate HTTP requests and emit safe access metadata."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = logging.getLogger("scms.access")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        header_value = _request_id_header(scope)
        request_id = normalize_request_id(header_value)
        scope.setdefault("state", {})["request_id"] = request_id
        token = set_request_id(request_id)
        started_at = perf_counter()
        status = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_ms = round((perf_counter() - started_at) * 1000, 3)
            try:
                self.logger.info(
                    "request.completed",
                    extra={
                        "request_id": request_id,
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status,
                        "duration_ms": duration_ms,
                    },
                )
            finally:
                reset_request_id(token)


def _request_id_header(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() == b"x-request-id":
            try:
                return value.decode("ascii")
            except UnicodeDecodeError:
                return None
    return None


configure_logging()

app = FastAPI(title="Student Club Management System API", version="0.1.0")
app.add_middleware(RequestContextMiddleware)
register_exception_handlers(app)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
