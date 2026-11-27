from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.security.password import hash_password
from app.db.session import DatabaseResources
from app.main import create_app
from app.modules.ai.config import AISettings
from app.modules.ai.models import AIToolExecution, AITurn, AIUsageRecord
from app.modules.clubs.models import Club, ClubCreationRequest, ClubMembership
from app.modules.events.models import Event
from app.modules.identity.auth_config import build_authentication_settings
from app.modules.identity.models import User
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
