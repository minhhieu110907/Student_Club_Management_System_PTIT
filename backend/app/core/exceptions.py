from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class AppException(Exception):
    """Base exception for safe, intentional application errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        error_code: str,
        details: Any | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details
        self.headers = dict(headers or {})


class BadRequestException(AppException):
    def __init__(self, message: str = "Bad request", *, details: Any | None = None) -> None:
        super().__init__(message, status_code=400, error_code="BAD_REQUEST", details=details)


class AuthenticationError(AppException):
    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__(
            message,
            status_code=401,
            error_code="UNAUTHORIZED",
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenError(AppException):
    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(message, status_code=403, error_code="FORBIDDEN")


class NotFoundException(AppException):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message, status_code=404, error_code="NOT_FOUND")


class ConflictException(AppException):
    def __init__(self, message: str = "Conflict", *, details: Any | None = None) -> None:
        super().__init__(message, status_code=409, error_code="CONFLICT", details=details)
