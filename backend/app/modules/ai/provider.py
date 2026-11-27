from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.core.exceptions import BadRequestException, ForbiddenError, NotFoundException
from app.modules.ai.config import AISettings
from app.modules.ai.exceptions import (
    AIProviderTimeoutError,
    AIProviderUnavailableError,
    AIToolBudgetExceededError,
    AIToolValidationError,
)
from app.modules.ai.tool_executor import BoundToolRequest

logger = logging.getLogger(__name__)

_EVENT_ID_PATTERN = re.compile(r"(?:event|sự kiện)\s*#?\s*(\d+)", re.IGNORECASE)

_SYSTEM_INSTRUCTION = (
    "You are the Student Club Management System (SCMS) assistant. "
    "Answer concisely and accurately in the same language as the user. "
    "Use only the provided read-only tools to look up upcoming events, "
    "the user's event registrations, the user's assigned tasks, or event task progress. "
    "Never invent data or claim actions were performed; you have read-only access only."
)


@dataclass(frozen=True, slots=True)
class AIProviderResult:
    reply: str
    provider: Literal["mock", "gemini"]
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    provider_request_id: str | None = None


class AIProvider(Protocol):
    def generate_reply(
        self,
        *,
        prompt: str,
        history: list[tuple[str, str]],
        bound_request: BoundToolRequest,
    ) -> AIProviderResult: ...


class MockAIProvider:
    """Deterministic local AI provider for demo and offline testing without an API key."""

    def __init__(self, model: str = "mock-scms-v1") -> None:
        self._model = model

    def generate_reply(
        self,
        *,
        prompt: str,
        history: list[tuple[str, str]],
        bound_request: BoundToolRequest,
    ) -> AIProviderResult:
        del history
        tool_name, arguments = self._select_tool(prompt)
        try:
            result = bound_request.executor.execute(
                tool_name=tool_name,
                arguments=arguments,
                context=bound_request.context,
            )
            reply = self._format_tool_reply(tool_name, result.data)
        except (AIProviderTimeoutError, AIToolBudgetExceededError):
            raise
        except (
            ForbiddenError,
            NotFoundException,
            BadRequestException,
            AIToolValidationError,
        ) as exc:
            reply = f"Unable to complete lookup ({exc.error_code}): {exc.message}"

        return AIProviderResult(
            reply=reply,
            provider="mock",
            model=self._model,
            input_tokens=max(1, len(prompt) // 4),
            output_tokens=max(1, len(reply) // 4),
        )

    @staticmethod
    def _select_tool(prompt: str) -> tuple[str, dict[str, Any]]:
        lowered = prompt.casefold()
        if any(keyword in lowered for keyword in ("task", "nhiệm vụ", "công việc")):
            return "get_my_tasks", {"page": 1, "page_size": 10}
        if any(keyword in lowered for keyword in ("registration", "registered", "đăng ký")):
            return "get_my_registrations", {"page": 1, "page_size": 10}
        if any(keyword in lowered for keyword in ("progress", "tiến độ")):
            match = _EVENT_ID_PATTERN.search(prompt)
            if match:
                return "get_event_progress", {"event_id": int(match.group(1))}
        return "list_upcoming_events", {"page": 1, "page_size": 10}

    @staticmethod
    def _format_tool_reply(tool_name: str, data: dict[str, Any]) -> str:
        if tool_name == "list_upcoming_events":
            items = data.get("items", [])
            if not items:
                return "There are currently no upcoming events visible to your account."
            titles = ", ".join(str(item.get("title", "Untitled")) for item in items[:5])
            return f"Upcoming events ({data.get('total', len(items))} total): {titles}."
        if tool_name == "get_my_registrations":
            items = data.get("items", [])
            if not items:
                return "You have no event registrations."
            summary = ", ".join(
                f"{item.get('event_title', 'Event')} ({item.get('status', 'UNKNOWN')})"
                for item in items[:5]
            )
            return f"Your registrations ({data.get('total', len(items))} total): {summary}."
        if tool_name == "get_my_tasks":
            items = data.get("items", [])
            if not items:
                return "You have no assigned event tasks."
            summary = ", ".join(
                f"{item.get('title', 'Task')} [{item.get('status', 'TODO')}]" for item in items[:5]
            )
            return f"Your assigned tasks ({data.get('total', len(items))} total): {summary}."
        if tool_name == "get_event_progress":
            return (
                f"Event #{data.get('event_id')} task progress: "
                f"{data.get('done', 0)}/{data.get('total', 0)} done "
                f"(TODO: {data.get('todo', 0)}, IN_PROGRESS: {data.get('in_progress', 0)})."
            )
        return "Completed read-only lookup."


def _build_gemini_tools() -> list[types.Tool]:
    declarations = [
        types.FunctionDeclaration(
            name="list_upcoming_events",
            description="List upcoming club events visible to the current authenticated user.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "club_id": types.Schema(
                        type=types.Type.INTEGER, description="Optional club ID"
                    ),
                    "visibility": types.Schema(
                        type=types.Type.STRING,
                        enum=["PUBLIC_STUDENTS", "CLUB_MEMBERS_ONLY"],
                        description="Optional visibility filter",
                    ),
                    "page": types.Schema(type=types.Type.INTEGER, description="Page number >= 1"),
                    "page_size": types.Schema(
                        type=types.Type.INTEGER, description="Items per page (1-50)"
                    ),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="get_my_registrations",
            description="List event registrations belonging to the current authenticated user.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "status": types.Schema(
                        type=types.Type.STRING,
                        enum=["REGISTERED", "CANCELLED"],
                        description="Optional registration status filter",
                    ),
                    "page": types.Schema(type=types.Type.INTEGER, description="Page number >= 1"),
                    "page_size": types.Schema(
                        type=types.Type.INTEGER, description="Items per page (1-50)"
                    ),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="get_my_tasks",
            description="List event tasks assigned to the current authenticated user.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "status": types.Schema(
                        type=types.Type.STRING,
                        enum=["TODO", "IN_PROGRESS", "DONE"],
                        description="Optional task status filter",
                    ),
                    "page": types.Schema(type=types.Type.INTEGER, description="Page number >= 1"),
                    "page_size": types.Schema(
                        type=types.Type.INTEGER, description="Items per page (1-50)"
                    ),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="get_event_progress",
            description="Get task progress summary for an event (requires active club manager role).",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "event_id": types.Schema(
                        type=types.Type.INTEGER, description="Target event ID"
                    ),
                },
                required=["event_id"],
            ),
        ),
    ]
    return [types.Tool(function_declarations=declarations)]


class GeminiAIProvider:
    """Google Gemini provider using the official google-genai SDK with manual tool loop."""

    def __init__(self, settings: AISettings, client: Any | None = None) -> None:
        if not settings.gemini_api_key and client is None:
            raise AIProviderUnavailableError("Gemini API key is not configured")
        self._settings = settings
        self._client = client or genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=int(settings.timeout_seconds * 1000)),
        )
        self._tools = _build_gemini_tools()

    def generate_reply(
        self,
        *,
        prompt: str,
        history: list[tuple[str, str]],
        bound_request: BoundToolRequest,
    ) -> AIProviderResult:
        contents: list[types.Content] = []
        for role, text in history:
            gemini_role = "user" if role == "USER" else "model"
            contents.append(
                types.Content(role=gemini_role, parts=[types.Part.from_text(text=text)])
            )
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=prompt)]))

        config = types.GenerateContentConfig(
            system_instruction=_SYSTEM_INSTRUCTION,
            tools=self._tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.1,
        )

        total_input_tokens = 0
        total_output_tokens = 0
        has_usage = False
        max_rounds = self._settings.max_tool_calls + 1

        for _round in range(max_rounds):
            bound_request.budget.check_deadline()
            response = self._call_gemini(contents=contents, config=config)

            usage = getattr(response, "usage_metadata", None)
            if usage is not None:
                has_usage = True
                total_input_tokens += int(getattr(usage, "prompt_token_count", 0) or 0)
                total_output_tokens += int(getattr(usage, "candidates_token_count", 0) or 0)

            function_calls = self._extract_function_calls(response)
            if not function_calls:
                reply_text = (getattr(response, "text", None) or "").strip()
                if not reply_text:
                    reply_text = "I could not generate a response for that request."
                return AIProviderResult(
                    reply=reply_text,
                    provider="gemini",
                    model=self._settings.gemini_model,
                    input_tokens=total_input_tokens if has_usage else None,
                    output_tokens=total_output_tokens if has_usage else None,
                    provider_request_id=getattr(response, "response_id", None),
                )

            model_content = response.candidates[0].content
            contents.append(model_content)

            tool_parts: list[types.Part] = []
            for call in function_calls:
                tool_name = str(getattr(call, "name", "") or "")
                raw_args = getattr(call, "args", None)
                arguments = dict(raw_args) if isinstance(raw_args, dict) else {}
                try:
                    tool_result = bound_request.executor.execute(
                        tool_name=tool_name,
                        arguments=arguments,
                        context=bound_request.context,
                    )
                    response_payload: dict[str, Any] = tool_result.data
                except (AIProviderTimeoutError, AIToolBudgetExceededError):
                    raise
                except (
                    ForbiddenError,
                    NotFoundException,
                    BadRequestException,
                    AIToolValidationError,
                ) as exc:
                    response_payload = {"error": exc.error_code, "message": exc.message}

                tool_parts.append(
                    types.Part.from_function_response(
                        name=tool_name or "unknown",
                        response=response_payload,
                    )
                )

            contents.append(types.Content(role="user", parts=tool_parts))

        raise AIToolBudgetExceededError("AI tool call limit exceeded for this request")

    def _call_gemini(
        self,
        *,
        contents: list[types.Content],
        config: types.GenerateContentConfig,
    ) -> Any:
        try:
            return self._client.models.generate_content(
                model=self._settings.gemini_model,
                contents=contents,
                config=config,
            )
        except TimeoutError as exc:
            raise AIProviderTimeoutError("Gemini API request timed out") from exc
        except genai_errors.APIError as exc:
            status_code = getattr(exc, "code", None)
            logger.warning("gemini_api_error", extra={"status_code": status_code})
            if status_code in {408, 504}:
                raise AIProviderTimeoutError("Gemini API request timed out") from exc
            raise AIProviderUnavailableError("Gemini AI provider request failed") from exc
        except Exception as exc:
            logger.warning("gemini_unexpected_error", extra={"error_type": type(exc).__name__})
            raise AIProviderUnavailableError("Gemini AI provider is unavailable") from exc

    @staticmethod
    def _extract_function_calls(response: Any) -> list[Any]:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return []
        content = getattr(candidates[0], "content", None)
        parts = getattr(content, "parts", None) or []
        calls: list[Any] = []
        for part in parts:
            function_call = getattr(part, "function_call", None)
            if function_call is not None:
                calls.append(function_call)
        return calls


def build_ai_provider(settings: AISettings) -> AIProvider:
    if settings.provider == "mock":
        return MockAIProvider()
    if settings.provider == "gemini":
        return GeminiAIProvider(settings)
    raise AIProviderUnavailableError(f"Unsupported AI provider: {settings.provider}")
