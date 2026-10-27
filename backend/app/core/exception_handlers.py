from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppException
from app.core.request_context import REQUEST_ID_HEADER, get_request_id
from app.core.response_models import APIErrorResponse

_HTTP_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
}
_SAFE_RESPONSE_HEADERS = {
    "allow": "Allow",
    "retry-after": "Retry-After",
    "www-authenticate": "WWW-Authenticate",
}


def register_exception_handlers(app: FastAPI) -> None:
    """Register the production error contract.

    Starlette intentionally bypasses the unexpected-error handler when an app
    runs with ``debug=True`` so developers receive its traceback response.
    SCMS runtime configuration must therefore keep debug mode disabled.
    """
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unexpected_exception_handler)


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Render an intentional application error whose details must be public-safe."""
    return _error_response(
        request,
        status_code=exc.status_code,
        message=exc.message,
        error_code=exc.error_code,
        details=exc.details,
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = [
        {
            "location": [str(part) if not isinstance(part, int) else part for part in error["loc"]],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    return _error_response(
        request,
        status_code=422,
        message="Request validation failed",
        error_code="VALIDATION_ERROR",
        details=details,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else _status_phrase(exc.status_code)
    return _error_response(
        request,
        status_code=exc.status_code,
        message=message,
        error_code=_HTTP_ERROR_CODES.get(exc.status_code, "HTTP_ERROR"),
        headers=exc.headers,
    )


async def unexpected_exception_handler(request: Request, _exc: Exception) -> JSONResponse:
    return _error_response(
        request,
        status_code=500,
        message="Internal server error",
        error_code="INTERNAL_SERVER_ERROR",
    )


def _error_response(
    request: Request,
    *,
    status_code: int,
    message: str,
    error_code: str,
    details: Any | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id() or "unavailable"
    response_headers = {
        canonical_name: value
        for key, value in (headers or {}).items()
        if (canonical_name := _SAFE_RESPONSE_HEADERS.get(key.lower())) is not None
    }
    response_headers[REQUEST_ID_HEADER] = request_id
    content = APIErrorResponse(
        message=message,
        error_code=error_code,
        details=details,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=content.model_dump(mode="json"),
        headers=response_headers,
    )


def _status_phrase(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "HTTP error"
