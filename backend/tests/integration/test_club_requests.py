from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.modules.clubs import service as club_service
from app.modules.clubs.exceptions import ClubRequestNotFoundError
from app.modules.clubs.models import Club, ClubCreationRequest, ClubMembership
from app.modules.clubs.schemas import ClubRequestCreate
from app.modules.identity.models import User
from app.modules.identity.schemas import CurrentUserResponse

DATABASE_URL = os.getenv("SCMS_CLUB_INTEGRATION_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="SCMS_CLUB_INTEGRATION_URL is required"),
]


@pytest.fixture
def engine() -> sa.Engine:
    assert DATABASE_URL is not None
    database_engine = sa.create_engine(DATABASE_URL, pool_pre_ping=True)
    with database_engine.begin() as connection:
        connection.execute(sa.delete(ClubMembership))
        connection.execute(sa.delete(Club))
        connection.execute(sa.delete(ClubCreationRequest))
        connection.execute(sa.delete(User))
        connection.execute(
            sa.insert(User),
            [
                _user_row(1, "student@example.com", "STUDENT"),
                _user_row(2, "other@example.com", "STUDENT"),
                _user_row(3, "admin@example.com", "ADMIN"),
                _user_row(4, "admin2@example.com", "ADMIN"),
            ],
        )
    try:
        yield database_engine
    finally:
        with database_engine.begin() as connection:
            connection.execute(sa.delete(ClubMembership))
            connection.execute(sa.delete(Club))
            connection.execute(sa.delete(ClubCreationRequest))
            connection.execute(sa.delete(User))
        database_engine.dispose()


def _user_row(user_id: int, email: str, role: str) -> dict[str, object]:
    now = datetime(2026, 10, 30)
    return {
        "id": user_id,
        "email_normalized": email,
        "full_name": email.split("@")[0],
        "password_hash": "unused",
        "global_role": role,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
    }


def _actor(user_id: int, role: str) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user_id,
        email=f"u{user_id}@example.com",
        full_name="Actor",
        global_role=role,
        status="ACTIVE",
    )


def _payload(name: str = "Engineering Club") -> ClubRequestCreate:
    return ClubRequestCreate(
        proposed_name=name,
        category="Academic",
        mission="Build practical engineering skills",
        initial_plan="Meet weekly and deliver projects",
    )


def _submit(engine: sa.Engine, name: str = "Engineering Club") -> int:
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        return club_service.submit_club_request(_payload(name), _actor(1, "STUDENT"), session).id


def test_student_submits_and_reads_valid_request(engine: sa.Engine) -> None:
    request_id = _submit(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        response = club_service.get_student_request(request_id, _actor(1, "STUDENT"), session)
    assert response.status == "PENDING"
    assert response.proposed_name == "Engineering Club"


def test_student_cannot_read_another_students_request(engine: sa.Engine) -> None:
    request_id = _submit(engine)
    with Session(engine) as session, pytest.raises(ClubRequestNotFoundError):
        club_service.get_student_request(request_id, _actor(2, "STUDENT"), session)


def test_approval_atomically_creates_club_and_founder_manager_once(engine: sa.Engine) -> None:
    request_id = _submit(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        first = club_service.approve_club_request(request_id, _actor(3, "ADMIN"), session)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        second = club_service.approve_club_request(request_id, _actor(3, "ADMIN"), session)
    assert first.status == second.status == "APPROVED"
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(Club)) == 1
        membership = connection.execute(sa.select(ClubMembership)).one()
    assert membership.user_id == 1
    assert membership.role == "MANAGER"
    assert membership.status == "ACTIVE"
    assert membership.source_application_id is None


def test_rejection_creates_no_club(engine: sa.Engine) -> None:
    request_id = _submit(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        response = club_service.reject_club_request(
            request_id, "Scope is unclear", _actor(3, "ADMIN"), session
        )
    assert response.status == "REJECTED"
    assert response.rejection_reason == "Scope is unclear"
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(Club)) == 0


def test_approval_failure_rolls_back_request_club_and_membership(
    engine: sa.Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_id = _submit(engine)

    def fail_after_club(session: Session, club: Club, _membership: ClubMembership) -> None:
        session.add(club)
        session.flush([club])
        raise RuntimeError("membership insert failed")

    monkeypatch.setattr(club_service, "add_approved_club", fail_after_club)
    with (
        Session(engine, autoflush=False, expire_on_commit=False) as session,
        pytest.raises(RuntimeError, match="membership insert failed"),
    ):
        club_service.approve_club_request(request_id, _actor(3, "ADMIN"), session)
    with engine.connect() as connection:
        request = connection.execute(sa.select(ClubCreationRequest)).one()
        assert request.status == "PENDING"
        assert connection.scalar(sa.select(sa.func.count()).select_from(Club)) == 0
        assert connection.scalar(sa.select(sa.func.count()).select_from(ClubMembership)) == 0


def test_concurrent_approvals_preserve_single_club_and_membership(
    engine: sa.Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_id = _submit(engine)
    barrier = threading.Barrier(2)
    real_lock = club_service.lock_club_request

    def synchronized_lock(session: Session, locked_id: int):
        barrier.wait(timeout=10)
        return real_lock(session, locked_id)

    monkeypatch.setattr(club_service, "lock_club_request", synchronized_lock)

    def approve(admin_id: int) -> str:
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            return club_service.approve_club_request(
                request_id, _actor(admin_id, "ADMIN"), session
            ).status

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(approve, (3, 4)))
    assert results == ["APPROVED", "APPROVED"]
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(Club)) == 1
        assert connection.scalar(sa.select(sa.func.count()).select_from(ClubMembership)) == 1
