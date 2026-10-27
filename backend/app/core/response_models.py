from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class APIErrorResponse(BaseModel):
    """Stable public envelope for API errors."""

    success: Literal[False] = False
    message: str
    error_code: str
    details: Any | None = None
    request_id: str
