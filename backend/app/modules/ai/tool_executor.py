from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import AppException, ForbiddenError
from app.modules.ai.budget import ToolBudget
from app.modules.ai.config import AISettings
from app.modules.ai.exceptions import (
    AIProviderTimeoutError,
    AIProviderUnavailableError,
    AIToolBudgetExceededError,
    AIToolValidationError,
)
from app.modules.ai.schemas import (
    GetEventProgressArgs,
    GetMyRegistrationsArgs,
    GetMyTasksArgs,
    ListUpcomingEventsArgs,
)
from app.modules.events.service import get_my_registrations, list_events
from app.modules.identity.schemas import CurrentUserResponse
from app.modules.tasks.service import get_event_task_progress, get_my_tasks

logger = logging.getLogger(__name__)

ToolId = Literal[
    "list_upcoming_events",
    "get_my_registrations",
    "get_my_tasks",
    "get_event_progress",
]

ALLOWED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "list_upcoming_events",
        "get_my_registrations",
        "get_my_tasks",
        "get_event_progress",
    }
)


@dataclass(frozen=True, eq=False, slots=True)
class ToolContext:
    """Opaque per-request capability bound to the authenticated JWT user."""

    user: CurrentUserResponse
    request_id: str


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    tool_name: ToolId
    data: dict[str, Any]
    serialized_bytes: bytes
    duration_ms: int


@dataclass(frozen=True, slots=True)
class ToolExecutionTrace:
    invocation_no: int
    tool_name: str
    status: Literal["SUCCEEDED", "FAILED", "DENIED", "TIMEOUT"]
    duration_ms: int
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class BoundToolRequest:
    context: ToolContext
    executor: AIToolExecutor
    budget: ToolBudget


def _serialize_tool_payload(tool_name: str, data: dict[str, Any]) -> bytes:
    return json.dumps(
        {"tool_name": tool_name, "data": data},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


class AIToolExecutor:
    """Strict allowlist dispatcher for read-only AI tools."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], AbstractContextManager[Session]] | None = None,
        session: Session | None = None,
        budget: ToolBudget | None = None,
        context_verifier: Callable[[ToolContext], bool] | None = None,
    ) -> None:
        if session_factory is None and session is None:
            raise ValueError("Either session_factory or session must be provided")
        self._session_factory = session_factory
        self._session = session
        self._budget = budget or ToolBudget()
        self._context_verifier = context_verifier
        self._traces: list[ToolExecutionTrace] = []

    @property
    def traces(self) -> tuple[ToolExecutionTrace, ...]:
        return tuple(self._traces)

    def _open_session(self) -> AbstractContextManager[Session]:
        if self._session_factory is not None:
            return self._session_factory()
        assert self._session is not None
        return nullcontext(self._session)

    def execute(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
        context: ToolContext,
    ) -> ToolExecutionResult:
        started = time.monotonic()
        trace_status: Literal["SUCCEEDED", "FAILED", "DENIED", "TIMEOUT"] = "FAILED"
        error_code: str | None = None
        verified = False
        invocation_no = len(self._traces) + 1

        try:
            with self._budget.lock:
                if self._context_verifier is None or not self._context_verifier(context):
                    trace_status = "DENIED"
                    error_code = "FORBIDDEN"
                    raise ForbiddenError("Invalid AI tool execution context")
                verified = True
                self._budget.check_deadline()
                self._budget.reserve()

                if tool_name not in ALLOWED_TOOL_NAMES:
                    error_code = "AI_TOOL_VALIDATION_ERROR"
                    raise AIToolValidationError(f"Tool '{tool_name}' is not allowlisted")

                if not isinstance(arguments, Mapping):
                    error_code = "AI_TOOL_VALIDATION_ERROR"
                    raise AIToolValidationError("Tool arguments must be an object")

                data = self._dispatch(tool_name, arguments, context.user)
                self._budget.check_deadline()
                payload = _serialize_tool_payload(tool_name, data)
                self._budget.add_output(payload)

                duration_ms = max(0, round((time.monotonic() - started) * 1000))
                trace_status = "SUCCEEDED"
                return ToolExecutionResult(
                    tool_name=tool_name,  # type: ignore[arg-type]
                    data=data,
                    serialized_bytes=payload,
                    duration_ms=duration_ms,
                )
        except AIProviderTimeoutError as exc:
            trace_status = "TIMEOUT"
            error_code = exc.error_code
            raise
        except AIToolBudgetExceededError as exc:
            trace_status = "DENIED"
            error_code = exc.error_code
            raise
        except ForbiddenError as exc:
            trace_status = "DENIED"
            error_code = exc.error_code
            raise
        except AppException as exc:
            trace_status = "FAILED"
            error_code = exc.error_code
            raise
        except Exception as exc:
            trace_status = "FAILED"
            error_code = "AI_PROVIDER_UNAVAILABLE"
            raise AIProviderUnavailableError("AI tool execution failed") from exc
        finally:
            duration_ms = max(0, round((time.monotonic() - started) * 1000))
            safe_name = tool_name if tool_name in ALLOWED_TOOL_NAMES else "unknown"
            self._traces.append(
                ToolExecutionTrace(
                    invocation_no=invocation_no,
                    tool_name=safe_name[:80],
                    status=trace_status,
                    duration_ms=duration_ms,
                    error_code=error_code,
                )
            )
            logger.info(
                "ai_tool_execution",
                extra={
                    "request_id": context.request_id if verified else "invalid",
                    "actor_id": context.user.id if verified else None,
                    "tool_name": safe_name,
                    "status": trace_status,
                    "duration_ms": duration_ms,
                    "error_code": error_code,
                },
            )

    def _dispatch(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        user: CurrentUserResponse,
    ) -> dict[str, Any]:
        args_model: type[BaseModel]
        if tool_name == "list_upcoming_events":
            args_model = ListUpcomingEventsArgs
        elif tool_name == "get_my_registrations":
            args_model = GetMyRegistrationsArgs
        elif tool_name == "get_my_tasks":
            args_model = GetMyTasksArgs
        elif tool_name == "get_event_progress":
            args_model = GetEventProgressArgs
        else:
            raise AIToolValidationError(f"Tool '{tool_name}' is not allowlisted")

        try:
            validated = args_model.model_validate(dict(arguments))
        except ValidationError as exc:
            raise AIToolValidationError("Invalid arguments for AI tool") from exc

        with self._open_session() as session:
            if isinstance(validated, ListUpcomingEventsArgs):
                response = list_events(
                    user,
                    session,
                    club_id=validated.club_id,
                    visibility=validated.visibility,
                    upcoming_only=True,
                    page=validated.page,
                    page_size=validated.page_size,
                )
            elif isinstance(validated, GetMyRegistrationsArgs):
                response = get_my_registrations(
                    user,
                    session,
                    status=validated.status,
                    page=validated.page,
                    page_size=validated.page_size,
                )
            elif isinstance(validated, GetMyTasksArgs):
                response = get_my_tasks(
                    user,
                    session,
                    status=validated.status,
                    page=validated.page,
                    page_size=validated.page_size,
                )
            elif isinstance(validated, GetEventProgressArgs):
                response = get_event_task_progress(
                    validated.event_id,
                    user,
                    session,
                )
            else:
                raise AIToolValidationError("Unsupported tool arguments")
            return response.model_dump(mode="json")


def bind_authenticated_request(
    user: CurrentUserResponse,
    *,
    request_id: str,
    settings: AISettings,
    session_factory: Callable[[], AbstractContextManager[Session]] | None = None,
    session: Session | None = None,
) -> BoundToolRequest:
    """Bind an authenticated JWT user to an isolated per-request tool executor and budget."""
    if not isinstance(user, CurrentUserResponse) or user.status != "ACTIVE":
        raise ForbiddenError("Active authenticated user is required")

    context = ToolContext(user=user, request_id=request_id)
    budget = ToolBudget(
        max_calls=settings.max_tool_calls,
        max_output_bytes=settings.max_tool_output_bytes,
        deadline_seconds=settings.request_deadline_seconds,
    )
    executor = AIToolExecutor(
        session_factory=session_factory,
        session=session,
        budget=budget,
        context_verifier=lambda supplied: supplied is context and supplied.user.id == user.id,
    )
    return BoundToolRequest(context=context, executor=executor, budget=budget)
