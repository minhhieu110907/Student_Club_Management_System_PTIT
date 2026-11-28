from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.security.password import hash_password
from app.db.session import DatabaseResources
from app.main import create_app
from app.modules.ai.config import AISettings
from app.modules.ai.exceptions import (
    AIConversationConflictError,
    AIProviderTimeoutError,
    AIProviderUnavailableError,
)
from app.modules.ai.models import (
    AIConversation,
    AIMessage,
    AIToolExecution,
    AITurn,
    AIUsageRecord,
)
from app.modules.ai.provider import AIProviderResult
from app.modules.ai.schemas import AIChatRequest
from app.modules.ai.service import chat_with_assistant
from app.modules.clubs.models import Club, ClubCreationRequest, ClubMembership
from app.modules.events.models import Event
from app.modules.identity.auth_config import build_authentication_settings
from app.modules.identity.models import User
from app.modules.identity.schemas import CurrentUserResponse
from app.modules.tasks.models import EventTask

pytestmark = pytest.mark.integration

_INTEGRATION_ENV = "SCMS_AI_INTEGRATION_URL"
_JWT_ENV = {
    "SCMS_ENV": "test",
    "SCMS_JWT_SECRET": "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE",
    "SCMS_JWT_ISSUER": "scms-test",
    "SCMS_JWT_AUDIENCE": "scms-api",
    "SCMS_AUTH_ALLOWED_ORIGINS": "http://localhost:8080",
    "SCMS_COOKIE_SECURE": "false",
}


def _get_session_factory() -> tuple[sessionmaker[Session], DatabaseResources]:
    url = os.getenv(_INTEGRATION_ENV, "").strip()
    if not url:
        pytest.skip(f"{_INTEGRATION_ENV} is not configured")
    engine = create_engine(url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return factory, DatabaseResources(engine=engine, session_factory=factory)


def _create_user(
    session: Session, email: str, full_name: str, global_role: str = "STUDENT"
) -> User:
    now = datetime.now(UTC).replace(tzinfo=None)
    user = User(
        email_normalized=email,
        password_hash=hash_password("StrongPass123!"),
        full_name=full_name,
        global_role=global_role,
        status="ACTIVE",
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    session.flush()
    return user


def _create_club(
    session: Session,
    *,
    name: str,
    category: str,
    description: str,
    owner_id: int,
    now: datetime,
) -> Club:
    req = ClubCreationRequest(
        requested_by=owner_id,
        proposed_name=name,
        category=category,
        mission=description,
        initial_plan="Workshops",
        status="APPROVED",
        reviewed_by=owner_id,
        reviewed_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(req)
    session.flush()
    club = Club(
        source_request_id=req.id,
        name=name,
        category=category,
        description=description,
        status="ACTIVE",
        created_at=now,
        updated_at=now,
    )
    session.add(club)
    session.flush()
    return club


def _login(client: TestClient, email: str) -> str:
    res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "StrongPass123!"},
        headers={"Origin": "http://localhost:8080"},
    )
    assert res.status_code == 200
    return res.json()["access_token"]


def test_ai_chat_mock_mode_enforces_club_visibility_and_persists_traces() -> None:
    factory, resources = _get_session_factory()
    try:
        now = datetime.now(UTC).replace(tzinfo=None)
        with factory() as session:
            manager = _create_user(session, "ai-mgr-1@example.edu", "AI Manager")
            _create_user(session, "ai-out-1@example.edu", "AI Outsider")
            club = _create_club(
                session,
                name="AI Robotics Club",
                category="Tech",
                description="Build robots",
                owner_id=manager.id,
                now=now,
            )
            session.add(
                ClubMembership(
                    club_id=club.id,
                    user_id=manager.id,
                    role="MANAGER",
                    status="ACTIVE",
                    joined_at=now,
                )
            )
            public_event = Event(
                club_id=club.id,
                created_by=manager.id,
                title="Public Robotics Expo",
                description="Open to all students",
                location="Main Hall",
                visibility="PUBLIC_STUDENTS",
                status="PUBLISHED",
                starts_at=now + timedelta(days=5),
                ends_at=now + timedelta(days=5, hours=2),
                registration_opens_at=now - timedelta(days=1),
                registration_closes_at=now + timedelta(days=4),
                capacity=100,
                published_at=now,
                created_at=now,
                updated_at=now,
            )
            private_event = Event(
                club_id=club.id,
                created_by=manager.id,
                title="Members Only Lab",
                description="Club members only",
                location="Lab 2",
                visibility="CLUB_MEMBERS_ONLY",
                status="PUBLISHED",
                starts_at=now + timedelta(days=6),
                ends_at=now + timedelta(days=6, hours=2),
                registration_opens_at=now - timedelta(days=1),
                registration_closes_at=now + timedelta(days=5),
                capacity=20,
                published_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add_all([public_event, private_event])
            session.commit()

        app = create_app(
            database_resources_factory=lambda: resources,
            authentication_settings_factory=lambda: build_authentication_settings(_JWT_ENV),
            ai_settings_factory=lambda: AISettings(
                "mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0
            ),
        )
        with TestClient(app) as client:
            outsider_token = _login(client, "ai-out-1@example.edu")
            res = client.post(
                "/api/v1/ai/chat",
                json={"message": "What upcoming events are available?"},
                headers={"Authorization": f"Bearer {outsider_token}"},
            )
            assert res.status_code == 200
            data = res.json()
            assert "Public Robotics Expo" in data["reply"]
            assert "Members Only Lab" not in data["reply"]
            assert data["tool_calls"][0]["tool_name"] == "list_upcoming_events"
            assert data["tool_calls"][0]["status"] == "SUCCEEDED"

            with factory() as session:
                turn = session.get(AITurn, data["turn_id"])
                assert turn is not None and turn.status == "SUCCEEDED"
                usage = session.execute(
                    select(AIUsageRecord).where(AIUsageRecord.turn_id == data["turn_id"])
                ).scalar_one()
                assert usage.status == "SUCCEEDED"
                tool_exec = session.execute(
                    select(AIToolExecution).where(AIToolExecution.turn_id == data["turn_id"])
                ).scalar_one()
                assert tool_exec.tool_name == "list_upcoming_events"
                assert tool_exec.status == "SUCCEEDED"
    finally:
        resources.dispose()


def test_ai_chat_enforces_event_progress_rbac_and_conversation_idor() -> None:
    factory, resources = _get_session_factory()
    try:
        now = datetime.now(UTC).replace(tzinfo=None)
        with factory() as session:
            manager = _create_user(session, "ai-mgr-2@example.edu", "AI Manager 2")
            member = _create_user(session, "ai-mem-2@example.edu", "AI Member 2")
            club = _create_club(
                session,
                name="AI Security Club",
                category="Tech",
                description="Learn security",
                owner_id=manager.id,
                now=now,
            )
            mgr_ms = ClubMembership(
                club_id=club.id, user_id=manager.id, role="MANAGER", status="ACTIVE", joined_at=now
            )
            mem_ms = ClubMembership(
                club_id=club.id, user_id=member.id, role="MEMBER", status="ACTIVE", joined_at=now
            )
            session.add_all([mgr_ms, mem_ms])
            session.flush()
            event = Event(
                club_id=club.id,
                created_by=manager.id,
                title="Security Workshop",
                description="Workshop",
                location="Room 101",
                visibility="PUBLIC_STUDENTS",
                status="PUBLISHED",
                starts_at=now + timedelta(days=3),
                ends_at=now + timedelta(days=3, hours=2),
                registration_opens_at=now - timedelta(days=1),
                registration_closes_at=now + timedelta(days=2),
                capacity=30,
                published_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(event)
            session.flush()
            event_id = event.id
            session.add(
                EventTask(
                    event_id=event_id,
                    club_id=club.id,
                    assignee_membership_id=mem_ms.id,
                    created_by=manager.id,
                    title="Prepare slides",
                    status="DONE",
                    completed_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

        app = create_app(
            database_resources_factory=lambda: resources,
            authentication_settings_factory=lambda: build_authentication_settings(_JWT_ENV),
            ai_settings_factory=lambda: AISettings(
                "mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0
            ),
        )
        with TestClient(app) as client:
            mgr_token = _login(client, "ai-mgr-2@example.edu")
            mem_token = _login(client, "ai-mem-2@example.edu")

            mgr_res = client.post(
                "/api/v1/ai/chat",
                json={"message": f"Check progress for event {event_id}"},
                headers={"Authorization": f"Bearer {mgr_token}"},
            )
            assert mgr_res.status_code == 200
            assert "1/1 done" in mgr_res.json()["reply"]
            conv_id = mgr_res.json()["conversation_id"]

            mem_res = client.post(
                "/api/v1/ai/chat",
                json={"message": f"Check progress for event {event_id}"},
                headers={"Authorization": f"Bearer {mem_token}"},
            )
            assert mem_res.status_code == 200
            assert "CLUB_MANAGER_REQUIRED" in mem_res.json()["reply"]
            assert mem_res.json()["tool_calls"][0]["status"] == "DENIED"

            idor_get = client.get(
                f"/api/v1/ai/conversations/{conv_id}",
                headers={"Authorization": f"Bearer {mem_token}"},
            )
            assert idor_get.status_code == 404

            idor_post = client.post(
                "/api/v1/ai/chat",
                json={"conversation_id": conv_id, "message": "Hijack"},
                headers={"Authorization": f"Bearer {mem_token}"},
            )
            assert idor_post.status_code == 404

            mem_tasks = client.post(
                "/api/v1/ai/chat",
                json={"message": "What are my tasks?"},
                headers={"Authorization": f"Bearer {mem_token}"},
            )
            assert mem_tasks.status_code == 200
            assert "Prepare slides" in mem_tasks.json()["reply"]
    finally:
        resources.dispose()


def test_ai_stale_turn_recovery_and_non_app_exception_persistence() -> None:
    factory, resources = _get_session_factory()
    try:
        now = datetime.now(UTC).replace(tzinfo=None)
        with factory() as session:
            user = _create_user(session, "ai-rec-1@example.edu", "Recovery User")
            conv = AIConversation(
                owner_user_id=user.id,
                title="Stale turn test",
                next_turn_no=2,
                created_at=now - timedelta(minutes=5),
                updated_at=now - timedelta(minutes=5),
                purge_after=now + timedelta(days=90),
            )
            session.add(conv)
            session.flush()
            stale_turn = AITurn(
                conversation_id=conv.id,
                client_request_key=uuid.uuid4().bytes,
                payload_hash=b"0" * 32,
                turn_no=1,
                status="RUNNING",
                lease_generation=1,
                lease_expires_at=now - timedelta(seconds=10),
                created_at=now - timedelta(minutes=5),
            )
            session.add(stale_turn)
            session.flush()
            session.add(
                AIUsageRecord(
                    turn_id=stale_turn.id,
                    attempt_no=1,
                    provider="mock",
                    model="mock-scms-v1",
                    status="PENDING",
                    usage_source="UNKNOWN",
                    created_at=now - timedelta(minutes=5),
                    purge_after=now + timedelta(days=90),
                )
            )
            conv_id = conv.id
            stale_turn_id = stale_turn.id
            user_dto = CurrentUserResponse(
                id=user.id,
                email=user.email_normalized,
                full_name=user.full_name,
                global_role=user.global_role,  # type: ignore[arg-type]
                status=user.status,  # type: ignore[arg-type]
            )
            session.commit()

        app = create_app(
            database_resources_factory=lambda: resources,
            authentication_settings_factory=lambda: build_authentication_settings(_JWT_ENV),
            ai_settings_factory=lambda: AISettings(
                "mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0
            ),
        )
        with TestClient(app) as client:
            token = _login(client, "ai-rec-1@example.edu")
            res = client.post(
                "/api/v1/ai/chat",
                json={"conversation_id": conv_id, "message": "What upcoming events?"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res.status_code == 200

        with factory() as session:
            recovered = session.get(AITurn, stale_turn_id)
            assert recovered is not None
            assert recovered.status == "FAILED"
            assert recovered.error_code == "AI_TURN_LEASE_EXPIRED"
            assert recovered.lease_generation == 2
            usage = session.execute(
                select(AIUsageRecord).where(AIUsageRecord.turn_id == stale_turn_id)
            ).scalar_one()
            assert usage.status == "TIMEOUT"

        class ExplodingProvider:
            def generate_reply(self, *, prompt, history, bound_request):
                raise RuntimeError("unexpected boom")

        with factory() as session:
            with pytest.raises(AIProviderUnavailableError):
                chat_with_assistant(
                    AIChatRequest(conversation_id=conv_id, message="Crash me"),
                    user_dto,
                    session,
                    settings=AISettings("mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0),
                    request_id="req-crash-int",
                    provider=ExplodingProvider(),  # type: ignore[arg-type]
                )

        with factory() as session:
            last_turn = (
                session.execute(
                    select(AITurn)
                    .where(AITurn.conversation_id == conv_id)
                    .order_by(AITurn.turn_no.desc())
                )
                .scalars()
                .first()
            )
            assert last_turn is not None
            assert last_turn.status == "FAILED"
            assert last_turn.error_code == "AI_INTERNAL_ERROR"
    finally:
        resources.dispose()


def test_ai_stale_worker_fencing_and_concurrent_recovery_race() -> None:
    factory, resources = _get_session_factory()
    try:
        now = datetime.now(UTC).replace(tzinfo=None)
        with factory() as session:
            user = _create_user(session, "ai-fence-1@example.edu", "Fence User")
            conv = AIConversation(
                owner_user_id=user.id,
                title="Fence test",
                next_turn_no=1,
                created_at=now,
                updated_at=now,
                purge_after=now + timedelta(days=90),
            )
            session.add(conv)
            session.flush()
            conv_id = conv.id
            user_dto = CurrentUserResponse(
                id=user.id,
                email=user.email_normalized,
                full_name=user.full_name,
                global_role=user.global_role,  # type: ignore[arg-type]
                status=user.status,  # type: ignore[arg-type]
            )
            session.commit()

        entered_provider = threading.Event()
        release_stale_worker = threading.Event()

        class SlowStaleProvider:
            def generate_reply(self, *, prompt, history, bound_request):
                entered_provider.set()
                release_stale_worker.wait(timeout=10)
                return AIProviderResult(
                    reply="STALE_OVERWRITE",
                    provider="mock",
                    model="mock-scms-v1",
                )

        def run_stale_worker() -> Exception | None:
            with factory() as s:
                try:
                    chat_with_assistant(
                        AIChatRequest(conversation_id=conv_id, message="Slow request"),
                        user_dto,
                        s,
                        settings=AISettings("mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0),
                        request_id="req-stale-worker",
                        provider=SlowStaleProvider(),  # type: ignore[arg-type]
                    )
                    return None
                except Exception as exc:
                    return exc

        with ThreadPoolExecutor(max_workers=1) as pool:
            stale_future = pool.submit(run_stale_worker)
            assert entered_provider.wait(timeout=5)

            with factory() as session:
                turn_1 = session.execute(
                    select(AITurn).where(AITurn.conversation_id == conv_id, AITurn.turn_no == 1)
                ).scalar_one()
                turn_1.lease_expires_at = _past = datetime.now(UTC).replace(
                    tzinfo=None
                ) - timedelta(seconds=5)
                del _past
                session.commit()

            barrier = threading.Barrier(2)

            def concurrent_recovery(idx: int) -> str:
                barrier.wait(timeout=5)
                with factory() as s:
                    try:
                        res = chat_with_assistant(
                            AIChatRequest(conversation_id=conv_id, message=f"Recover {idx}"),
                            user_dto,
                            s,
                            settings=AISettings(
                                "mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0
                            ),
                            request_id=f"req-rec-{idx}",
                        )
                        return f"OK:{res.turn_id}"
                    except AIConversationConflictError:
                        return "CONFLICT"

            with ThreadPoolExecutor(max_workers=2) as rec_pool:
                rec_results = list(rec_pool.map(concurrent_recovery, [1, 2]))

            assert sorted(rec_results)[0] == "CONFLICT"
            assert sorted(rec_results)[1].startswith("OK:")

            release_stale_worker.set()
            stale_exc = stale_future.result(timeout=10)
            assert isinstance(stale_exc, AIConversationConflictError)

        with factory() as session:
            assistant_msgs = (
                session.execute(
                    select(AIMessage).where(
                        AIMessage.conversation_id == conv_id, AIMessage.role == "ASSISTANT"
                    )
                )
                .scalars()
                .all()
            )
            assert len(assistant_msgs) == 1
            assert assistant_msgs[0].content != "STALE_OVERWRITE"
    finally:
        resources.dispose()


def test_ai_chat_idempotency_replay_conflict_and_concurrent_same_key() -> None:
    factory, resources = _get_session_factory()
    try:
        now = datetime.now(UTC).replace(tzinfo=None)
        with factory() as session:
            user = _create_user(session, "ai-idem-1@example.edu", "Idem User")
            conv = AIConversation(
                owner_user_id=user.id,
                title="Idem test",
                next_turn_no=1,
                created_at=now,
                updated_at=now,
                purge_after=now + timedelta(days=90),
            )
            session.add(conv)
            session.flush()
            conv_id = conv.id
            user_dto = CurrentUserResponse(
                id=user.id,
                email=user.email_normalized,
                full_name=user.full_name,
                global_role=user.global_role,  # type: ignore[arg-type]
                status=user.status,  # type: ignore[arg-type]
            )
            session.commit()

        call_count = 0
        count_lock = threading.Lock()

        class CountingProvider:
            def generate_reply(self, *, prompt, history, bound_request):
                with count_lock:
                    nonlocal call_count
                    call_count += 1
                    num = call_count
                return AIProviderResult(
                    reply=f"Reply #{num}",
                    provider="mock",
                    model="mock-scms-v1",
                    input_tokens=10,
                    output_tokens=4,
                )

        req_key = uuid.uuid4()
        settings = AISettings("mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0)
        with factory() as session:
            first = chat_with_assistant(
                AIChatRequest(
                    conversation_id=conv_id,
                    message="Hello idempotency",
                    client_request_key=req_key,
                ),
                user_dto,
                session,
                settings=settings,
                request_id="req-idem-1",
                provider=CountingProvider(),  # type: ignore[arg-type]
            )
        with factory() as session:
            replay = chat_with_assistant(
                AIChatRequest(
                    conversation_id=conv_id,
                    message="Hello idempotency",
                    client_request_key=req_key,
                ),
                user_dto,
                session,
                settings=settings,
                request_id="req-idem-2",
                provider=CountingProvider(),  # type: ignore[arg-type]
            )
        assert replay.turn_id == first.turn_id
        assert replay.message_id == first.message_id
        assert replay.reply == "Reply #1"
        assert call_count == 1

        with factory() as session:
            with pytest.raises(AIConversationConflictError):
                chat_with_assistant(
                    AIChatRequest(
                        conversation_id=conv_id,
                        message="Different payload",
                        client_request_key=req_key,
                    ),
                    user_dto,
                    session,
                    settings=settings,
                    request_id="req-idem-3",
                    provider=CountingProvider(),  # type: ignore[arg-type]
                )

        race_key = uuid.uuid4()
        barrier = threading.Barrier(2)

        def concurrent_same_key(idx: int) -> str:
            barrier.wait(timeout=5)
            with factory() as s:
                try:
                    res = chat_with_assistant(
                        AIChatRequest(
                            conversation_id=conv_id,
                            message="Concurrent same key",
                            client_request_key=race_key,
                        ),
                        user_dto,
                        s,
                        settings=settings,
                        request_id=f"req-race-{idx}",
                        provider=CountingProvider(),  # type: ignore[arg-type]
                    )
                    return f"OK:{res.turn_id}"
                except AIConversationConflictError:
                    return "CONFLICT"

        with ThreadPoolExecutor(max_workers=2) as pool:
            race_outcomes = list(pool.map(concurrent_same_key, [1, 2]))

        assert any(item.startswith("OK:") for item in race_outcomes)
        assert call_count == 2
        with factory() as session:
            matching_turns = session.execute(
                select(func.count())
                .select_from(AITurn)
                .where(
                    AITurn.conversation_id == conv_id,
                    AITurn.client_request_key == race_key.bytes,
                )
            ).scalar_one()
            assert matching_turns == 1
    finally:
        resources.dispose()


def test_ai_session_lifecycle_has_no_open_transaction_during_provider_call() -> None:
    factory, resources = _get_session_factory()
    try:
        with factory() as session:
            user = _create_user(session, "ai-tx-1@example.edu", "TX User")
            user_dto = CurrentUserResponse(
                id=user.id,
                email=user.email_normalized,
                full_name=user.full_name,
                global_role=user.global_role,  # type: ignore[arg-type]
                status=user.status,  # type: ignore[arg-type]
            )
            session.commit()

        observed_in_tx: list[bool] = []
        with factory() as session:

            class InspectingProvider:
                def generate_reply(self, *, prompt, history, bound_request):
                    observed_in_tx.append(session.in_transaction())
                    return AIProviderResult(
                        reply="Clean session",
                        provider="mock",
                        model="mock-scms-v1",
                    )

            res = chat_with_assistant(
                AIChatRequest(message="Check tx state"),
                user_dto,
                session,
                settings=AISettings("mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0),
                request_id="req-tx-check",
                provider=InspectingProvider(),  # type: ignore[arg-type]
            )
            assert res.reply == "Clean session"
        assert observed_in_tx == [False]
    finally:
        resources.dispose()


def test_ai_new_conversation_concurrent_idempotency_and_payload_conflict() -> None:
    factory, resources = _get_session_factory()
    try:
        with factory() as session:
            user = _create_user(session, "ai-newconv-1@example.edu", "New Conv User")
            user_dto = CurrentUserResponse(
                id=user.id,
                email=user.email_normalized,
                full_name=user.full_name,
                global_role=user.global_role,  # type: ignore[arg-type]
                status=user.status,  # type: ignore[arg-type]
            )
            session.commit()

        call_count = 0
        count_lock = threading.Lock()

        class NewConvProvider:
            def generate_reply(self, *, prompt, history, bound_request):
                with count_lock:
                    nonlocal call_count
                    call_count += 1
                return AIProviderResult(
                    reply="Created once",
                    provider="mock",
                    model="mock-scms-v1",
                    input_tokens=8,
                    output_tokens=3,
                )

        create_key = uuid.uuid4()
        settings = AISettings("mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0)
        barrier = threading.Barrier(2)

        def create_concurrent(idx: int) -> str:
            barrier.wait(timeout=5)
            with factory() as s:
                try:
                    res = chat_with_assistant(
                        AIChatRequest(
                            conversation_id=None,
                            message="Start new conversation",
                            client_request_key=create_key,
                        ),
                        user_dto,
                        s,
                        settings=settings,
                        request_id=f"req-newconv-{idx}",
                        provider=NewConvProvider(),  # type: ignore[arg-type]
                    )
                    return f"OK:{res.conversation_id}:{res.turn_id}"
                except AIConversationConflictError:
                    return "CONFLICT"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(create_concurrent, [1, 2]))

        assert any(o.startswith("OK:") for o in outcomes)
        assert call_count == 1

        with factory() as session:
            conv_count = session.execute(
                select(func.count())
                .select_from(AIConversation)
                .where(AIConversation.owner_user_id == user_dto.id)
            ).scalar_one()
            assert conv_count == 1

            with pytest.raises(AIConversationConflictError):
                chat_with_assistant(
                    AIChatRequest(
                        conversation_id=None,
                        message="Different new conversation message",
                        client_request_key=create_key,
                    ),
                    user_dto,
                    session,
                    settings=settings,
                    request_id="req-newconv-diff",
                    provider=NewConvProvider(),  # type: ignore[arg-type]
                )
    finally:
        resources.dispose()


def test_ai_failed_turn_idempotency_replays_saved_error_without_reexecuting() -> None:
    factory, resources = _get_session_factory()
    try:
        with factory() as session:
            user = _create_user(session, "ai-failidem-1@example.edu", "Fail Idem User")
            user_dto = CurrentUserResponse(
                id=user.id,
                email=user.email_normalized,
                full_name=user.full_name,
                global_role=user.global_role,  # type: ignore[arg-type]
                status=user.status,  # type: ignore[arg-type]
            )
            session.commit()

        call_count = 0

        class TimeoutProvider:
            def generate_reply(self, *, prompt, history, bound_request):
                nonlocal call_count
                call_count += 1
                raise AIProviderTimeoutError("Simulated timeout")

        fail_key = uuid.uuid4()
        settings = AISettings("mock", None, "gemini-2.5-flash", 15.0, 3, 32768, 15.0)

        with factory() as session:
            with pytest.raises(AIProviderTimeoutError):
                chat_with_assistant(
                    AIChatRequest(
                        conversation_id=None,
                        message="Trigger timeout",
                        client_request_key=fail_key,
                    ),
                    user_dto,
                    session,
                    settings=settings,
                    request_id="req-fail-1",
                    provider=TimeoutProvider(),  # type: ignore[arg-type]
                )

        with factory() as session:
            with pytest.raises(AIProviderTimeoutError):
                chat_with_assistant(
                    AIChatRequest(
                        conversation_id=None,
                        message="Trigger timeout",
                        client_request_key=fail_key,
                    ),
                    user_dto,
                    session,
                    settings=settings,
                    request_id="req-fail-2",
                    provider=TimeoutProvider(),  # type: ignore[arg-type]
                )

        assert call_count == 1
        with factory() as session:
            usage_count = session.execute(
                select(func.count())
                .select_from(AIUsageRecord)
                .join(AITurn, AIUsageRecord.turn_id == AITurn.id)
                .join(AIConversation, AITurn.conversation_id == AIConversation.id)
                .where(AIConversation.owner_user_id == user_dto.id)
            ).scalar_one()
            assert usage_count == 1
    finally:
        resources.dispose()
