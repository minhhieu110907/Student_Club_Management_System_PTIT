from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ForbiddenError
from app.db.session import get_db_session
from app.main import create_app
from app.modules.ai.config import AISettings
from app.modules.ai.exceptions import (
    AIIdempotencyKeyReusedError,
    AIProviderTimeoutError,
    AIProviderUnavailableError,
    AIToolBudgetExceededError,
    AITurnInProgressError,
)
from app.modules.ai.provider import GeminiAIProvider, MockAIProvider
from app.modules.ai.schemas import AIChatRequest
from app.modules.ai.service import (
    _compute_payload_hash,
    _resolve_existing_turn,
    chat_with_assistant,
)
from app.modules.ai.tool_executor import bind_authenticated_request
from app.modules.identity.auth_config import build_authentication_settings
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.schemas import CurrentUserResponse
from app.modules.tasks.schemas import EventTaskListResponse, EventTaskProgressResponse


def _student(user_id: int = 10) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user_id,
        email="student@example.edu",
        full_name="Student User",
        global_role="STUDENT",
        status="ACTIVE",
    )


def _gemini_settings() -> AISettings:
    return AISettings(
        provider="gemini",
        gemini_api_key="super-secret-gemini-key",
        gemini_model="gemini-2.5-flash",
        timeout_seconds=10.0,
        max_tool_calls=3,
        max_tool_output_bytes=32 * 1024,
        request_deadline_seconds=15.0,
    )


def test_mock_provider_handles_tasks_and_forbidden_progress(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.ai.tool_executor.get_my_tasks",
        lambda u, s, **kwargs: EventTaskListResponse(items=[], page=1, page_size=10, total=0),
    )

    def deny_progress(event_id, u, s):
        raise ForbiddenError("Manager role required")

    monkeypatch.setattr("app.modules.ai.tool_executor.get_event_task_progress", deny_progress)

    provider = MockAIProvider()
    bound_tasks = bind_authenticated_request(
        _student(),
        request_id="req-m1",
        settings=AISettings("mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0),
        session=MagicMock(),
    )
    res_tasks = provider.generate_reply(
        prompt="Show my tasks",
        history=[],
        bound_request=bound_tasks,
    )
    assert "no assigned event tasks" in res_tasks.reply.lower()

    bound_prog = bind_authenticated_request(
        _student(),
        request_id="req-m2",
        settings=AISettings("mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0),
        session=MagicMock(),
    )
    res_prog = provider.generate_reply(
        prompt="Show progress for event 5",
        history=[],
        bound_request=bound_prog,
    )
    assert "FORBIDDEN" in res_prog.reply


def test_gemini_provider_executes_tool_call_and_returns_final_reply(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.ai.tool_executor.get_event_task_progress",
        lambda event_id, u, s: EventTaskProgressResponse(
            event_id=event_id,
            todo=2,
            in_progress=1,
            done=3,
            total=6,
            completion_percentage=50.0,
        ),
    )

    first_response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    role="model",
                    parts=[
                        SimpleNamespace(
                            function_call=SimpleNamespace(
                                name="get_event_progress",
                                args={"event_id": 12},
                            )
                        )
                    ],
                )
            )
        ],
        usage_metadata=SimpleNamespace(prompt_token_count=20, candidates_token_count=8),
        text=None,
        response_id="resp-1",
    )
    second_response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(role="model", parts=[SimpleNamespace(function_call=None)])
            )
        ],
        usage_metadata=SimpleNamespace(prompt_token_count=35, candidates_token_count=15),
        text="Event 12 has 3 of 6 tasks done.",
        response_id="resp-2",
    )

    fake_models = MagicMock()
    fake_models.generate_content.side_effect = [first_response, second_response]
    fake_client = SimpleNamespace(models=fake_models)

    provider = GeminiAIProvider(_gemini_settings(), client=fake_client)
    bound = bind_authenticated_request(
        _student(),
        request_id="req-g1",
        settings=_gemini_settings(),
        session=MagicMock(),
    )

    result = provider.generate_reply(
        prompt="How is event 12 progressing?",
        history=[],
        bound_request=bound,
    )
    assert result.provider == "gemini"
    assert result.reply == "Event 12 has 3 of 6 tasks done."
    assert result.input_tokens == 55
    assert result.output_tokens == 23
    assert len(bound.executor.traces) == 1
    assert bound.executor.traces[0].tool_name == "get_event_progress"
    assert bound.executor.traces[0].status == "SUCCEEDED"


def test_gemini_provider_blocks_infinite_tool_loop_at_budget_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.ai.tool_executor.get_my_tasks",
        lambda u, s, **kwargs: EventTaskListResponse(items=[], page=1, page_size=20, total=0),
    )
    tool_response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    role="model",
                    parts=[
                        SimpleNamespace(function_call=SimpleNamespace(name="get_my_tasks", args={}))
                    ],
                )
            )
        ],
        usage_metadata=None,
        text=None,
        response_id="resp-loop",
    )
    fake_models = MagicMock()
    fake_models.generate_content.return_value = tool_response
    provider = GeminiAIProvider(_gemini_settings(), client=SimpleNamespace(models=fake_models))
    bound = bind_authenticated_request(
        _student(),
        request_id="req-g2",
        settings=_gemini_settings(),
        session=MagicMock(),
    )

    with pytest.raises(AIToolBudgetExceededError):
        provider.generate_reply(prompt="Loop forever", history=[], bound_request=bound)
    assert bound.budget.calls == 3


def test_gemini_provider_sanitizes_timeout_and_sdk_errors() -> None:
    fake_models_timeout = MagicMock()
    fake_models_timeout.generate_content.side_effect = TimeoutError("socket timed out")
    provider_timeout = GeminiAIProvider(
        _gemini_settings(), client=SimpleNamespace(models=fake_models_timeout)
    )
    bound = bind_authenticated_request(
        _student(),
        request_id="req-t1",
        settings=_gemini_settings(),
        session=MagicMock(),
    )
    with pytest.raises(AIProviderTimeoutError):
        provider_timeout.generate_reply(prompt="Hi", history=[], bound_request=bound)

    fake_models_err = MagicMock()
    fake_models_err.generate_content.side_effect = RuntimeError("super-secret-gemini-key leaked")
    provider_err = GeminiAIProvider(
        _gemini_settings(), client=SimpleNamespace(models=fake_models_err)
    )
    bound_err = bind_authenticated_request(
        _student(),
        request_id="req-t2",
        settings=_gemini_settings(),
        session=MagicMock(),
    )
    with pytest.raises(AIProviderUnavailableError) as exc_info:
        provider_err.generate_reply(prompt="Hi", history=[], bound_request=bound_err)
    assert "super-secret-gemini-key" not in exc_info.value.message


def test_chat_service_commits_before_calling_provider(monkeypatch) -> None:
    events_order: list[str] = []

    class FakeSession:
        def __init__(self) -> None:
            self._next_id = 1

        def add(self, obj) -> None:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1

        def add_all(self, objs) -> None:
            for obj in objs:
                self.add(obj)

        def flush(self) -> None:
            pass

        def commit(self) -> None:
            events_order.append("commit")

        def rollback(self) -> None:
            events_order.append("rollback")

        def get(self, model, ident):
            return SimpleNamespace(id=ident, status="PENDING")

        def execute(self, stmt):
            return SimpleNamespace(rowcount=1)

        def get_bind(self):
            return None

    class FakeProvider:
        def generate_reply(self, *, prompt, history, bound_request):
            events_order.append("provider_call")
            return SimpleNamespace(
                reply="Hello!",
                provider="mock",
                model="mock-scms-v1",
                input_tokens=5,
                output_tokens=2,
                provider_request_id=None,
            )

    from contextlib import nullcontext

    response = chat_with_assistant(
        AIChatRequest(message="Hello"),
        _student(),
        FakeSession(),  # type: ignore[arg-type]
        settings=AISettings("mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0),
        request_id="req-tx",
        provider=FakeProvider(),  # type: ignore[arg-type]
        tool_session_factory=lambda: nullcontext(MagicMock()),  # type: ignore[arg-type]
    )
    assert response.reply == "Hello!"
    assert events_order == ["commit", "provider_call", "commit"]


def test_gemini_provider_shrinks_http_timeout_by_remaining_budget(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.ai.tool_executor.get_my_tasks",
        lambda u, s, **kwargs: EventTaskListResponse(items=[], page=1, page_size=20, total=0),
    )
    recorded_timeouts: list[int] = []
    first_response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    role="model",
                    parts=[
                        SimpleNamespace(function_call=SimpleNamespace(name="get_my_tasks", args={}))
                    ],
                )
            )
        ],
        usage_metadata=None,
        text=None,
        response_id="r-1",
    )
    second_response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(role="model", parts=[SimpleNamespace(function_call=None)])
            )
        ],
        usage_metadata=None,
        text="Done.",
        response_id="r-2",
    )

    def fake_generate_content(*, model, contents, config):
        recorded_timeouts.append(config.http_options.timeout)
        if len(recorded_timeouts) == 1:
            bound.budget.started_at -= 8.0
            return first_response
        return second_response

    fake_models = MagicMock()
    fake_models.generate_content.side_effect = fake_generate_content
    provider = GeminiAIProvider(_gemini_settings(), client=SimpleNamespace(models=fake_models))
    bound = bind_authenticated_request(
        _student(),
        request_id="req-timeout-shrink",
        settings=_gemini_settings(),
        session=MagicMock(),
    )

    result = provider.generate_reply(prompt="Tasks?", history=[], bound_request=bound)
    assert result.reply == "Done."
    assert len(recorded_timeouts) == 2
    assert recorded_timeouts[1] <= recorded_timeouts[0] - 2000


def test_gemini_provider_disables_sdk_retries_and_stops_when_remaining_near_zero() -> None:
    recorded_attempts: list[int | None] = []
    first_response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    role="model",
                    parts=[
                        SimpleNamespace(function_call=SimpleNamespace(name="get_my_tasks", args={}))
                    ],
                )
            )
        ],
        usage_metadata=None,
        text=None,
        response_id="r-edge",
    )

    def fake_generate_content(*, model, contents, config):
        recorded_attempts.append(config.http_options.retry_options.attempts)
        bound.budget.started_at -= 15.0
        return first_response

    fake_models = MagicMock()
    fake_models.generate_content.side_effect = fake_generate_content
    provider = GeminiAIProvider(_gemini_settings(), client=SimpleNamespace(models=fake_models))
    bound = bind_authenticated_request(
        _student(),
        request_id="req-near-zero",
        settings=_gemini_settings(),
        session=MagicMock(),
    )

    with pytest.raises(AIProviderTimeoutError):
        provider.generate_reply(prompt="Tasks?", history=[], bound_request=bound)
    assert recorded_attempts == [1]
    assert fake_models.generate_content.call_count == 1


def test_chat_service_handles_non_app_exception_and_marks_turn_failed() -> None:
    from contextlib import nullcontext

    added_objects: list[object] = []

    class FakeSession:
        def __init__(self) -> None:
            self._next_id = 1

        def add(self, obj) -> None:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1
            added_objects.append(obj)

        def add_all(self, objs) -> None:
            for obj in objs:
                self.add(obj)

        def flush(self) -> None:
            pass

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def get(self, model, ident):
            return SimpleNamespace(id=ident, status="PENDING")

        def execute(self, stmt):
            return SimpleNamespace(rowcount=1)

        def get_bind(self):
            return None

    class ExplodingProvider:
        def generate_reply(self, *, prompt, history, bound_request):
            raise RuntimeError("unexpected secret-leaking crash")

    with pytest.raises(AIProviderUnavailableError) as exc_info:
        chat_with_assistant(
            AIChatRequest(message="Crash please"),
            _student(),
            FakeSession(),  # type: ignore[arg-type]
            settings=AISettings("mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0),
            request_id="req-crash",
            provider=ExplodingProvider(),  # type: ignore[arg-type]
            tool_session_factory=lambda: nullcontext(MagicMock()),  # type: ignore[arg-type]
        )
    assert "secret-leaking" not in exc_info.value.message


def test_ai_router_requires_authentication_and_validates_payload() -> None:
    auth_settings = build_authentication_settings(
        {
            "SCMS_JWT_SECRET": "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE",
            "SCMS_JWT_ISSUER": "scms-test",
            "SCMS_JWT_AUDIENCE": "scms-api",
            "SCMS_AUTH_ALLOWED_ORIGINS": "http://localhost:8080",
        }
    )
    app = create_app(
        database_resources_factory=lambda: None,
        authentication_settings_factory=lambda: auth_settings,
        ai_settings_factory=lambda: AISettings(
            "mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0
        ),
    )
    app.dependency_overrides[get_db_session] = lambda: MagicMock()
    with TestClient(app) as client:
        unauth = client.post("/api/v1/ai/chat", json={"message": "Upcoming events?"})
        assert unauth.status_code == 401

        app.dependency_overrides[get_current_user] = lambda: _student()
        invalid = client.post("/api/v1/ai/chat", json={"message": "", "user_id": 999})
        assert invalid.status_code == 422


def test_ai_router_chat_endpoint_returns_mock_response(monkeypatch) -> None:
    app = create_app(
        database_resources_factory=lambda: None,
        authentication_settings_factory=lambda: None,
        ai_settings_factory=lambda: AISettings(
            "mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0
        ),
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    monkeypatch.setattr(
        "app.modules.ai.router.chat_with_assistant",
        lambda payload, user, session, **kwargs: {
            "conversation_id": 1,
            "turn_id": 1,
            "message_id": 2,
            "provider": "mock",
            "model": "mock-scms-v1",
            "reply": "Upcoming events (0 total): none.",
            "tool_calls": [
                {"tool_name": "list_upcoming_events", "status": "SUCCEEDED", "duration_ms": 1}
            ],
            "data_retrieved_at": now,
        },
    )
    app.dependency_overrides[get_current_user] = lambda: _student()
    app.dependency_overrides[get_db_session] = lambda: MagicMock()

    with TestClient(app) as client:
        response = client.post("/api/v1/ai/chat", json={"message": "What events are coming up?"})
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "mock"
        assert body["tool_calls"][0]["tool_name"] == "list_upcoming_events"


def test_idempotency_error_codes_distinguish_in_progress_reused_and_saved_failure() -> None:
    payload_hash = _compute_payload_hash(prompt="Hello", club_context_id=None)
    other_hash = _compute_payload_hash(prompt="Different", club_context_id=None)

    running_turn = SimpleNamespace(status="RUNNING", payload_hash=payload_hash, error_code=None)
    with pytest.raises(AITurnInProgressError) as in_prog_exc:
        _resolve_existing_turn(MagicMock(), existing_turn=running_turn, payload_hash=payload_hash)
    assert in_prog_exc.value.status_code == 409
    assert in_prog_exc.value.error_code == "AI_TURN_IN_PROGRESS"

    with pytest.raises(AIIdempotencyKeyReusedError) as reused_exc:
        _resolve_existing_turn(MagicMock(), existing_turn=running_turn, payload_hash=other_hash)
    assert reused_exc.value.status_code == 409
    assert reused_exc.value.error_code == "AI_IDEMPOTENCY_KEY_REUSED"

    failed_turn = SimpleNamespace(
        status="FAILED", payload_hash=payload_hash, error_code="AI_PROVIDER_TIMEOUT"
    )
    with pytest.raises(AIProviderTimeoutError) as failed_exc:
        _resolve_existing_turn(MagicMock(), existing_turn=failed_turn, payload_hash=payload_hash)
    assert failed_exc.value.status_code == 504
    assert failed_exc.value.error_code == "AI_PROVIDER_TIMEOUT"


def test_ai_router_maps_idempotency_error_codes_in_http_409_responses(monkeypatch) -> None:
    app = create_app(
        database_resources_factory=lambda: None,
        authentication_settings_factory=lambda: None,
        ai_settings_factory=lambda: AISettings(
            "mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0
        ),
    )
    app.dependency_overrides[get_current_user] = lambda: _student()
    app.dependency_overrides[get_db_session] = lambda: MagicMock()

    with TestClient(app) as client:
        monkeypatch.setattr(
            "app.modules.ai.router.chat_with_assistant",
            lambda *args, **kwargs: (_ for _ in ()).throw(AITurnInProgressError()),
        )
        r1 = client.post("/api/v1/ai/chat", json={"message": "Hi"})
        assert r1.status_code == 409
        assert r1.json()["error_code"] == "AI_TURN_IN_PROGRESS"

        monkeypatch.setattr(
            "app.modules.ai.router.chat_with_assistant",
            lambda *args, **kwargs: (_ for _ in ()).throw(AIIdempotencyKeyReusedError()),
        )
        r2 = client.post("/api/v1/ai/chat", json={"message": "Hi"})
        assert r2.status_code == 409
        assert r2.json()["error_code"] == "AI_IDEMPOTENCY_KEY_REUSED"


def test_post_phase1_init_failures_persist_turn_failure_and_preserve_original_error(
    monkeypatch,
) -> None:
    from contextlib import nullcontext

    def _make_session(*, fail_claim_commit: bool = False, claim_rowcount: int = 1):
        recorded_claims: list[dict] = []

        class FakeSession:
            def __init__(self) -> None:
                self._next_id = 1
                self.commits = 0
                self.rollbacks = 0

            def add(self, obj) -> None:
                if getattr(obj, "id", None) is None:
                    obj.id = self._next_id
                    self._next_id += 1

            def add_all(self, objs) -> None:
                for obj in objs:
                    self.add(obj)

            def flush(self) -> None:
                pass

            def commit(self) -> None:
                self.commits += 1
                if fail_claim_commit and self.commits > 1:
                    raise RuntimeError("db commit failed during failure persistence")

            def rollback(self) -> None:
                self.rollbacks += 1

            def get(self, model, ident):
                return SimpleNamespace(id=ident, status="PENDING")

            def execute(self, stmt):
                recorded_claims.append({"stmt": str(stmt)})
                return SimpleNamespace(rowcount=claim_rowcount)

            def get_bind(self):
                return None

        return FakeSession(), recorded_claims

    settings = AISettings("mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0)

    # 1. Provider factory raises
    s1, claims1 = _make_session()
    with monkeypatch.context() as mp:
        mp.setattr(
            "app.modules.ai.service.build_ai_provider",
            lambda _s: (_ for _ in ()).throw(RuntimeError("provider init boom")),
        )
        with pytest.raises(AIProviderUnavailableError):
            chat_with_assistant(
                AIChatRequest(message="Hi"),
                _student(),
                s1,  # type: ignore[arg-type]
                settings=settings,
                request_id="req-p1",
                tool_session_factory=lambda: nullcontext(MagicMock()),  # type: ignore[arg-type]
            )
    assert len(claims1) == 1
    assert s1.commits == 2

    # 2. Tool session factory raises
    s2, claims2 = _make_session()
    with pytest.raises(AIProviderUnavailableError):
        chat_with_assistant(
            AIChatRequest(message="Hi"),
            _student(),
            s2,  # type: ignore[arg-type]
            settings=settings,
            request_id="req-p2",
            provider=MockAIProvider(),  # type: ignore[arg-type]
            tool_session_factory=lambda: (_ for _ in ()).throw(
                RuntimeError("session factory boom")
            ),
        )
    assert len(claims2) == 1
    assert s2.commits == 2

    # 3. bind_authenticated_request raises
    s3, claims3 = _make_session()
    with monkeypatch.context() as mp:
        mp.setattr(
            "app.modules.ai.service.bind_authenticated_request",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("bind boom")),
        )
        with pytest.raises(AIProviderUnavailableError):
            chat_with_assistant(
                AIChatRequest(message="Hi"),
                _student(),
                s3,  # type: ignore[arg-type]
                settings=settings,
                request_id="req-p3",
                provider=MockAIProvider(),  # type: ignore[arg-type]
                tool_session_factory=lambda: nullcontext(MagicMock()),  # type: ignore[arg-type]
            )
    assert len(claims3) == 1
    assert s3.commits == 2

    # 4. Failure persistence error does not mask original AppException and fencing rollbacks
    s4, _ = _make_session(fail_claim_commit=True)
    with pytest.raises(AIProviderTimeoutError):
        chat_with_assistant(
            AIChatRequest(message="Hi"),
            _student(),
            s4,  # type: ignore[arg-type]
            settings=settings,
            request_id="req-p4",
            provider=SimpleNamespace(
                generate_reply=lambda **kwargs: (_ for _ in ()).throw(
                    AIProviderTimeoutError("original timeout")
                )
            ),  # type: ignore[arg-type]
            tool_session_factory=lambda: nullcontext(MagicMock()),  # type: ignore[arg-type]
        )
    assert s4.rollbacks >= 1

    # 5. Stale worker fencing when claim_turn_completion returns 0 rows
    s5, _ = _make_session(claim_rowcount=0)
    with pytest.raises(AIProviderTimeoutError):
        chat_with_assistant(
            AIChatRequest(message="Hi"),
            _student(),
            s5,  # type: ignore[arg-type]
            settings=settings,
            request_id="req-p5",
            provider=SimpleNamespace(
                generate_reply=lambda **kwargs: (_ for _ in ()).throw(
                    AIProviderTimeoutError("late timeout")
                )
            ),  # type: ignore[arg-type]
            tool_session_factory=lambda: nullcontext(MagicMock()),  # type: ignore[arg-type]
        )
    assert s5.rollbacks >= 1
