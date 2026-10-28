from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from contextlib import asynccontextmanager
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
from app.db.session import DatabaseResources, build_database_resources
from app.health.router import router as health_router
from app.health.service import ReadinessService, build_readiness_service
from app.modules.identity.router import router as identity_router


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


def create_app(
    readiness_service_factory: Callable[[], ReadinessService] = build_readiness_service,
    database_resources_factory: Callable[[], DatabaseResources | None] = build_database_resources,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        readiness_service = readiness_service_factory()
        try:
            database_resources = database_resources_factory()
        except BaseException:
            try:
                readiness_service.dispose()
            except BaseException:
                pass
            raise
        application.state.readiness_service = readiness_service
        application.state.database_resources = database_resources
        try:
            yield
        finally:
            original_error = sys.exception()
            cleanup_error: BaseException | None = None
            try:
                if database_resources is not None:
                    database_resources.dispose()
            except BaseException as exc:
                cleanup_error = exc
            try:
                readiness_service.dispose()
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc
            if original_error is None and cleanup_error is not None:
                raise cleanup_error

    application = FastAPI(
        title="Student Club Management System API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(RequestContextMiddleware)
    register_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(identity_router)
    return application


app = create_app()
