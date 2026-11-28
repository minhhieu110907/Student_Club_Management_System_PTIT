from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from app.modules.ai.exceptions import AIConfigurationError

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_AI_TIMEOUT_SECONDS = 15.0
DEFAULT_AI_MAX_TOOL_CALLS = 3
DEFAULT_AI_MAX_TOOL_OUTPUT_BYTES = 32 * 1024
DEFAULT_AI_REQUEST_DEADLINE_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class AISettings:
    """Validated AI provider and tool-execution budget configuration."""

    provider: Literal["mock", "gemini"]
    gemini_api_key: str | None
    gemini_model: str
    timeout_seconds: float
    max_tool_calls: int
    max_tool_output_bytes: int
    request_deadline_seconds: float


def _parse_positive_float(raw: str | None, default: float, name: str) -> float:
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise AIConfigurationError(f"{name} must be a valid number") from exc
    if value <= 0 or value > 60:
        raise AIConfigurationError(f"{name} must be > 0 and <= 60")
    return value


def _parse_positive_int(raw: str | None, default: int, name: str, maximum: int) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise AIConfigurationError(f"{name} must be a valid integer") from exc
    if value <= 0 or value > maximum:
        raise AIConfigurationError(f"{name} must be between 1 and {maximum}")
    return value


def build_ai_settings(environment: Mapping[str, str] | None = None) -> AISettings:
    """Build and fail-closed validate AI configuration from environment variables."""
    values = os.environ if environment is None else environment
    raw_provider = values.get("AI_PROVIDER", "mock").strip().casefold()
    if raw_provider not in {"mock", "gemini"}:
        raise AIConfigurationError("AI_PROVIDER must be 'mock' or 'gemini'")

    gemini_api_key = values.get("GEMINI_API_KEY", "").strip() or None
    if raw_provider == "gemini" and not gemini_api_key:
        raise AIConfigurationError("GEMINI_API_KEY must be set when AI_PROVIDER=gemini")

    gemini_model = values.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
    timeout_seconds = _parse_positive_float(
        values.get("AI_PROVIDER_TIMEOUT_SECONDS"),
        DEFAULT_AI_TIMEOUT_SECONDS,
        "AI_PROVIDER_TIMEOUT_SECONDS",
    )
    max_tool_calls = _parse_positive_int(
        values.get("AI_MAX_TOOL_CALLS"),
        DEFAULT_AI_MAX_TOOL_CALLS,
        "AI_MAX_TOOL_CALLS",
        10,
    )
    max_tool_output_bytes = _parse_positive_int(
        values.get("AI_MAX_TOOL_OUTPUT_BYTES"),
        DEFAULT_AI_MAX_TOOL_OUTPUT_BYTES,
        "AI_MAX_TOOL_OUTPUT_BYTES",
        256 * 1024,
    )
    request_deadline_seconds = _parse_positive_float(
        values.get("AI_REQUEST_DEADLINE_SECONDS"),
        DEFAULT_AI_REQUEST_DEADLINE_SECONDS,
        "AI_REQUEST_DEADLINE_SECONDS",
    )

    return AISettings(
        provider=raw_provider,  # type: ignore[arg-type]
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        timeout_seconds=timeout_seconds,
        max_tool_calls=max_tool_calls,
        max_tool_output_bytes=max_tool_output_bytes,
        request_deadline_seconds=request_deadline_seconds,
    )
