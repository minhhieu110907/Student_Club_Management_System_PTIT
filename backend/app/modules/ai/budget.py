from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import RLock

from app.modules.ai.exceptions import AIProviderTimeoutError, AIToolBudgetExceededError

AI_MAX_TOOL_CALLS = 3
AI_MAX_TOOL_OUTPUT_BYTES = 32 * 1024
AI_REQUEST_DEADLINE_SECONDS = 15.0


@dataclass
class ToolBudget:
    """Request-owned mutable execution budget shared across all tool calls in one AI turn."""

    started_at: float = 0.0
    calls: int = 0
    output_bytes: int = 0
    max_calls: int = AI_MAX_TOOL_CALLS
    max_output_bytes: int = AI_MAX_TOOL_OUTPUT_BYTES
    deadline_seconds: float = AI_REQUEST_DEADLINE_SECONDS
    lock: RLock = field(default_factory=RLock, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.started_at == 0.0:
            self.started_at = time.monotonic()

    def remaining_seconds(self) -> float:
        return self.deadline_seconds - (time.monotonic() - self.started_at)

    def check_deadline(self) -> None:
        if self.remaining_seconds() <= 0:
            raise AIProviderTimeoutError("AI request exceeded execution time budget")

    def reserve(self) -> None:
        self.check_deadline()
        if self.calls >= self.max_calls:
            raise AIToolBudgetExceededError("AI tool call limit exceeded for this request")
        self.calls += 1

    def add_output(self, payload: bytes) -> None:
        self.check_deadline()
        if self.output_bytes + len(payload) > self.max_output_bytes:
            raise AIToolBudgetExceededError("AI tool output size limit exceeded for this request")
        self.output_bytes += len(payload)
