from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import ForbiddenError
from app.modules.ai.budget import ToolBudget
from app.modules.ai.config import AISettings, build_ai_settings
from app.modules.ai.exceptions import (
    AIConfigurationError,
    AIProviderTimeoutError,
    AIToolBudgetExceededError,
    AIToolValidationError,
)
from app.modules.ai.tool_executor import ToolContext, bind_authenticated_request
from app.modules.events.schemas import (
    EventListResponse,
    EventResponse,
    MyRegistrationListResponse,
)
from app.modules.identity.schemas import CurrentUserResponse
from app.modules.tasks.schemas import EventTaskListResponse, EventTaskProgressResponse


def _active_user(user_id: int = 10) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user_id,
        email="student@example.edu",
        full_name="Test Student",
        global_role="STUDENT",
        status="ACTIVE",
    )


def _mock_settings(
    *,
    max_tool_calls: int = 3,
    max_tool_output_bytes: int = 32 * 1024,
    request_deadline_seconds: float = 15.0,
) -> AISettings:
    return AISettings(
        provider="mock",
        gemini_api_key=None,
        gemini_model="gemini-2.5-flash",
        timeout_seconds=15.0,
        max_tool_calls=max_tool_calls,
        max_tool_output_bytes=max_tool_output_bytes,
        request_deadline_seconds=request_deadline_seconds,
    )


def test_build_ai_settings_defaults_to_mock() -> None:
    settings = build_ai_settings({})
    assert settings.provider == "mock"
    assert settings.gemini_api_key is None
    assert settings.max_tool_calls == 3
    assert settings.max_tool_output_bytes == 32 * 1024
    assert settings.request_deadline_seconds == 15.0


def test_build_ai_settings_gemini_requires_api_key_fail_closed() -> None:
    with pytest.raises(AIConfigurationError):
        build_ai_settings({"AI_PROVIDER": "gemini"})

    settings = build_ai_settings({"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "secret-key"})
    assert settings.provider == "gemini"
    assert settings.gemini_api_key == "secret-key"


def test_build_ai_settings_rejects_unknown_provider() -> None:
    with pytest.raises(AIConfigurationError):
        build_ai_settings({"AI_PROVIDER": "openai"})


def test_tool_executor_rejects_non_allowlisted_tool_and_consumes_budget() -> None:
    bound = bind_authenticated_request(
        _active_user(),
        request_id="req-1",
        settings=_mock_settings(),
        session=MagicMock(),
    )

    with pytest.raises(AIToolValidationError):
        bound.executor.execute(
            tool_name="run_raw_sql",
            arguments={},
            context=bound.context,
        )

    assert bound.budget.calls == 1


def test_tool_executor_rejects_forged_user_id_argument() -> None:
    bound = bind_authenticated_request(
        _active_user(),
        request_id="req-2",
        settings=_mock_settings(),
        session=MagicMock(),
    )

    with pytest.raises(AIToolValidationError):
        bound.executor.execute(
            tool_name="get_my_tasks",
            arguments={"user_id": 999},
            context=bound.context,
        )


def test_tool_executor_rejects_forged_context() -> None:
    user = _active_user(10)
    bound = bind_authenticated_request(
        user,
        request_id="req-3",
        settings=_mock_settings(),
        session=MagicMock(),
    )
    forged_context = ToolContext(user=_active_user(99), request_id="req-3")

    with pytest.raises(ForbiddenError):
        bound.executor.execute(
            tool_name="get_my_tasks",
            arguments={},
            context=forged_context,
        )


def test_tool_budget_enforces_max_calls_and_independent_per_request(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.ai.tool_executor.get_my_tasks",
        lambda user, session, **kwargs: EventTaskListResponse(
            items=[], page=1, page_size=20, total=0
        ),
    )
    bound_1 = bind_authenticated_request(
        _active_user(10),
        request_id="req-a",
        settings=_mock_settings(max_tool_calls=3),
        session=MagicMock(),
    )

    for _ in range(3):
        bound_1.executor.execute(
            tool_name="get_my_tasks",
            arguments={},
            context=bound_1.context,
        )

    with pytest.raises(AIToolBudgetExceededError):
        bound_1.executor.execute(
            tool_name="get_my_tasks",
            arguments={},
            context=bound_1.context,
        )

    bound_2 = bind_authenticated_request(
        _active_user(10),
        request_id="req-b",
        settings=_mock_settings(max_tool_calls=3),
        session=MagicMock(),
    )
    res = bound_2.executor.execute(
        tool_name="get_my_tasks",
        arguments={},
        context=bound_2.context,
    )
    assert res.tool_name == "get_my_tasks"


def test_tool_budget_enforces_32kib_cumulative_output_cap(monkeypatch) -> None:
    large_title = "A" * 18000
    now = datetime.now(UTC).replace(tzinfo=None)
    monkeypatch.setattr(
        "app.modules.ai.tool_executor.list_events",
        lambda user, session, **kwargs: EventListResponse(
            items=[
                EventResponse(
                    id=1,
                    club_id=1,
                    club_name="Tech Club",
                    created_by=1,
                    title=large_title,
                    description="Tech talk",
                    location="Hall A",
                    visibility="PUBLIC_STUDENTS",
                    status="PUBLISHED",
                    starts_at=now,
                    ends_at=now,
                    registration_opens_at=now,
                    registration_closes_at=now,
                    cancellation_deadline_at=None,
                    capacity=50,
                    registration_count=1,
                    is_registered=False,
                    version=1,
                    published_at=now,
                    cancelled_at=None,
                    cancellation_reason=None,
                    created_at=now,
                    updated_at=now,
                )
            ],
            page=1,
            page_size=20,
            total=1,
        ),
    )

    bound = bind_authenticated_request(
        _active_user(10),
        request_id="req-bytes",
        settings=_mock_settings(max_tool_calls=3, max_tool_output_bytes=32 * 1024),
        session=MagicMock(),
    )

    first = bound.executor.execute(
        tool_name="list_upcoming_events",
        arguments={},
        context=bound.context,
    )
    assert len(first.serialized_bytes) > 18000

    with pytest.raises(AIToolBudgetExceededError):
        bound.executor.execute(
            tool_name="list_upcoming_events",
            arguments={},
            context=bound.context,
        )


def test_tool_budget_enforces_deadline_seconds() -> None:
    budget = ToolBudget(started_at=time.monotonic() - 16.0, deadline_seconds=15.0)
    with pytest.raises(AIProviderTimeoutError):
        budget.reserve()


def test_tool_executor_dispatches_all_four_allowlisted_tools(monkeypatch) -> None:
    user = _active_user(42)
    captured_users: list[int] = []

    def fake_list_events(u, session, **kwargs):
        captured_users.append(u.id)
        assert kwargs["upcoming_only"] is True
        return EventListResponse(items=[], page=1, page_size=20, total=0)

    def fake_regs(u, session, **kwargs):
        captured_users.append(u.id)
        return MyRegistrationListResponse(items=[], page=1, page_size=20, total=0)

    def fake_tasks(u, session, **kwargs):
        captured_users.append(u.id)
        return EventTaskListResponse(items=[], page=1, page_size=20, total=0)

    def fake_progress(event_id, u, session):
        captured_users.append(u.id)
        assert event_id == 7
        return EventTaskProgressResponse(
            event_id=7,
            todo=1,
            in_progress=1,
            done=2,
            total=4,
            completion_percentage=50.0,
        )

    monkeypatch.setattr("app.modules.ai.tool_executor.list_events", fake_list_events)
    monkeypatch.setattr("app.modules.ai.tool_executor.get_my_registrations", fake_regs)
    monkeypatch.setattr("app.modules.ai.tool_executor.get_my_tasks", fake_tasks)
    monkeypatch.setattr("app.modules.ai.tool_executor.get_event_task_progress", fake_progress)

    bound = bind_authenticated_request(
        user,
        request_id="req-all-4",
        settings=_mock_settings(max_tool_calls=5),
        session=MagicMock(),
    )

    assert (
        bound.executor.execute(
            tool_name="list_upcoming_events", arguments={}, context=bound.context
        ).tool_name
        == "list_upcoming_events"
    )
    assert (
        bound.executor.execute(
            tool_name="get_my_registrations", arguments={}, context=bound.context
        ).tool_name
        == "get_my_registrations"
    )
    assert (
        bound.executor.execute(
            tool_name="get_my_tasks", arguments={}, context=bound.context
        ).tool_name
        == "get_my_tasks"
    )
    progress = bound.executor.execute(
        tool_name="get_event_progress", arguments={"event_id": 7}, context=bound.context
    )
    assert progress.data["total"] == 4
    assert captured_users == [42, 42, 42, 42]
