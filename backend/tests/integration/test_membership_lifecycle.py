from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.modules.clubs import service
from app.modules.clubs.exceptions import (
    ActiveMembershipExistsError,
    ClubManagerRequiredError,
    ManagerLeaveNotAllowedError,
    MembershipApplicationAlreadyReviewedError,
    PendingMembershipApplicationError,
    RemovedMembershipReapplicationError,
    StudentRoleRequiredError,
)
from app.modules.clubs.models import (
    Club,
    ClubCreationRequest,
    ClubMembership,
    MembershipApplication,
)
from app.modules.clubs.schemas import MembershipApplicationCreate
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
    _reset(database_engine)
    with database_engine.begin() as connection:
        connection.execute(
            sa.insert(User),
            [
                _user_row(1, "applicant@example.com", "STUDENT"),
                _user_row(2, "manager@example.com", "STUDENT"),
                _user_row(3, "other-manager@example.com", "STUDENT"),
                _user_row(4, "admin@example.com", "ADMIN"),
            ],
        )
        connection.execute(
            sa.insert(ClubCreationRequest),
            [
                _club_request_row(101, 2, "Club One"),
                _club_request_row(102, 3, "Club Two"),
            ],
        )
        connection.execute(
            sa.insert(Club),
            [
                _club_row(11, 101, "Club One"),
                _club_row(12, 102, "Club Two"),
            ],
        )
        connection.execute(
            sa.insert(ClubMembership),
            [
                _membership_row(201, 11, 2, "MANAGER"),
                _membership_row(202, 12, 3, "MANAGER"),
            ],
        )
    try:
        yield database_engine
    finally:
        _reset(database_engine)
        database_engine.dispose()


def _reset(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(sa.delete(ClubMembership))
        connection.execute(sa.delete(MembershipApplication))
        connection.execute(sa.delete(Club))
        connection.execute(sa.delete(ClubCreationRequest))
        connection.execute(sa.delete(User))


def _now() -> datetime:
    return datetime(2026, 11, 2)


def _user_row(user_id: int, email: str, role: str) -> dict[str, object]:
    return {
        "id": user_id,
        "email_normalized": email,
        "full_name": email.split("@")[0],
        "password_hash": "unused",
        "global_role": role,
        "status": "ACTIVE",
        "created_at": _now(),
        "updated_at": _now(),
    }


def _club_request_row(request_id: int, user_id: int, name: str) -> dict[str, object]:
    return {
        "id": request_id,
        "requested_by": user_id,
        "proposed_name": name,
        "category": "Academic",
        "mission": "Learn together",
        "initial_plan": "Meet weekly",
        "status": "APPROVED",
        "reviewed_by": 4,
        "reviewed_at": _now(),
        "rejection_reason": None,
        "created_at": _now(),
        "updated_at": _now(),
    }


def _club_row(club_id: int, request_id: int, name: str) -> dict[str, object]:
    return {
        "id": club_id,
        "source_request_id": request_id,
        "name": name,
        "category": "Academic",
        "description": "Learn together",
        "status": "ACTIVE",
        "created_at": _now(),
        "updated_at": _now(),
    }


def _membership_row(
    membership_id: int,
    club_id: int,
    user_id: int,
    role: str,
    *,
    status: str = "ACTIVE",
    source_application_id: int | None = None,
) -> dict[str, object]:
    return {
        "id": membership_id,
        "club_id": club_id,
        "user_id": user_id,
        "source_application_id": source_application_id,
        "role": role,
        "status": status,
        "joined_at": _now(),
        "ended_at": None if status == "ACTIVE" else _now(),
    }


def _actor(user_id: int, role: str = "STUDENT") -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user_id,
        email=f"u{user_id}@example.com",
        full_name=f"User {user_id}",
        global_role=role,
        status="ACTIVE",
    )


def _apply(engine: sa.Engine, club_id: int = 11) -> int:
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        return service.submit_membership_application(
            club_id,
            MembershipApplicationCreate(motivation="I want to contribute"),
            _actor(1),
            session,
        ).id


def test_apply_approve_leave_and_reapply_preserves_history(engine: sa.Engine) -> None:
    application_id = _apply(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        approved = service.approve_membership_application(application_id, _actor(2), session)
    assert approved.status == "APPROVED"

    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        membership = service.get_my_memberships(_actor(1), session)[0]
        session.rollback()
        left = service.leave_membership(membership.id, _actor(1), session)
    assert left.status == "LEFT"

    reapplied_id = _apply(engine)
    assert reapplied_id != application_id
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(MembershipApplication)) == 2
        assert connection.scalar(sa.select(sa.func.count()).select_from(ClubMembership)) == 3


def test_reapply_after_rejection_is_allowed(engine: sa.Engine) -> None:
    application_id = _apply(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        service.reject_membership_application(
            application_id, "Please add more detail", _actor(2), session
        )
    assert _apply(engine) != application_id


def test_reapply_after_removed_is_denied(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.insert(ClubMembership),
            _membership_row(203, 11, 1, "MEMBER", status="REMOVED"),
        )
    with Session(engine) as session, pytest.raises(RemovedMembershipReapplicationError):
        service.submit_membership_application(
            11, MembershipApplicationCreate(motivation="Try again"), _actor(1), session
        )


def test_cross_club_and_admin_bypass_are_denied(engine: sa.Engine) -> None:
    application_id = _apply(engine)
    with Session(engine) as session, pytest.raises(ClubManagerRequiredError):
        service.approve_membership_application(application_id, _actor(3), session)
    with Session(engine) as session, pytest.raises(StudentRoleRequiredError):
        service.approve_membership_application(application_id, _actor(4, "ADMIN"), session)


def test_inactive_manager_is_denied(engine: sa.Engine) -> None:
    application_id = _apply(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.update(ClubMembership)
            .where(ClubMembership.id == 201)
            .values(status="LEFT", ended_at=_now())
        )
    with Session(engine) as session, pytest.raises(ClubManagerRequiredError):
        service.approve_membership_application(application_id, _actor(2), session)


def test_duplicate_pending_application_is_denied(engine: sa.Engine) -> None:
    _apply(engine)
    with Session(engine) as session, pytest.raises(PendingMembershipApplicationError):
        service.submit_membership_application(
            11, MembershipApplicationCreate(motivation="Duplicate"), _actor(1), session
        )


def test_concurrent_applications_create_exactly_one_pending(engine: sa.Engine) -> None:
    start = threading.Barrier(2)

    def submit() -> str:
        start.wait(timeout=10)
        try:
            _apply(engine)
            return "created"
        except PendingMembershipApplicationError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: submit(), range(2)))
    assert sorted(results) == ["conflict", "created"]
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(MembershipApplication)) == 1


def test_concurrent_approve_approve_commits_one_decision(engine: sa.Engine) -> None:
    application_id = _apply(engine)
    start = threading.Barrier(2)

    def approve() -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                service.approve_membership_application(application_id, _actor(2), session)
            return "approved"
        except MembershipApplicationAlreadyReviewedError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: approve(), range(2)))
    assert sorted(results) == ["approved", "conflict"]
    _assert_single_approved_membership(engine)


def test_concurrent_approve_reject_commits_exactly_one_decision(engine: sa.Engine) -> None:
    application_id = _apply(engine)
    start = threading.Barrier(2)

    def decide(approve: bool) -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                if approve:
                    service.approve_membership_application(application_id, _actor(2), session)
                    return "APPROVED"
                service.reject_membership_application(
                    application_id, "Not this time", _actor(2), session
                )
                return "REJECTED"
        except MembershipApplicationAlreadyReviewedError:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(decide, (True, False)))
    assert results.count("CONFLICT") == 1
    winner = next(result for result in results if result != "CONFLICT")
    with engine.connect() as connection:
        application = connection.execute(sa.select(MembershipApplication)).one()
        member_count = connection.scalar(
            sa.select(sa.func.count())
            .select_from(ClubMembership)
            .where(ClubMembership.user_id == 1)
        )
    assert application.status == winner
    assert member_count == (1 if winner == "APPROVED" else 0)


def test_approval_failure_rolls_back_application(engine: sa.Engine, monkeypatch) -> None:
    application_id = _apply(engine)

    def fail_membership_insert(_session: Session, _membership: ClubMembership) -> None:
        raise RuntimeError("injected membership failure")

    monkeypatch.setattr(service, "add_membership", fail_membership_insert)
    with Session(engine) as session, pytest.raises(RuntimeError, match="injected"):
        service.approve_membership_application(application_id, _actor(2), session)
    with engine.connect() as connection:
        application = connection.execute(sa.select(MembershipApplication)).one()
        member_count = connection.scalar(
            sa.select(sa.func.count())
            .select_from(ClubMembership)
            .where(ClubMembership.user_id == 1)
        )
    assert application.status == "PENDING"
    assert member_count == 0


def test_member_leave_and_manager_self_leave_policy(engine: sa.Engine) -> None:
    application_id = _apply(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        service.approve_membership_application(application_id, _actor(2), session)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        member = next(item for item in service.get_my_memberships(_actor(1), session))
        session.rollback()
        assert service.leave_membership(member.id, _actor(1), session).status == "LEFT"
    with Session(engine) as session, pytest.raises(ManagerLeaveNotAllowedError):
        service.leave_membership(201, _actor(2), session)


def test_concurrent_application_and_leave_never_leave_active_with_pending(
    engine: sa.Engine,
) -> None:
    with engine.begin() as connection:
        connection.execute(sa.insert(ClubMembership), _membership_row(203, 11, 1, "MEMBER"))
    start = threading.Barrier(2)

    def apply() -> str:
        start.wait(timeout=10)
        try:
            _apply(engine)
            return "created"
        except ActiveMembershipExistsError:
            return "active"

    def leave() -> str:
        start.wait(timeout=10)
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            return service.leave_membership(203, _actor(1), session).status

    with ThreadPoolExecutor(max_workers=2) as executor:
        apply_future = executor.submit(apply)
        leave_future = executor.submit(leave)
        results = {apply_future.result(), leave_future.result()}
    assert "LEFT" in results
    with engine.connect() as connection:
        active_count = connection.scalar(
            sa.select(sa.func.count())
            .select_from(ClubMembership)
            .where(ClubMembership.user_id == 1, ClubMembership.status == "ACTIVE")
        )
        pending_count = connection.scalar(
            sa.select(sa.func.count())
            .select_from(MembershipApplication)
            .where(MembershipApplication.user_id == 1, MembershipApplication.status == "PENDING")
        )
    assert active_count == 0
    assert pending_count in {0, 1}


def test_concurrent_manager_leave_preserves_at_least_one_active_manager(
    engine: sa.Engine,
) -> None:
    with engine.begin() as connection:
        connection.execute(sa.insert(ClubMembership), _membership_row(204, 11, 1, "MANAGER"))

    start = threading.Barrier(2)

    def leave(membership_id: int, actor_id: int) -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                return service.leave_membership(membership_id, _actor(actor_id), session).status
        except ManagerLeaveNotAllowedError:
            return "BLOCKED"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(leave, 201, 2)
        second = executor.submit(leave, 204, 1)
        results = [first.result(), second.result()]

    assert results.count("LEFT") == 1
    assert results.count("BLOCKED") == 1
    with engine.connect() as connection:
        remaining_managers = connection.scalar(
            sa.select(sa.func.count())
            .select_from(ClubMembership)
            .where(
                ClubMembership.club_id == 11,
                ClubMembership.role == "MANAGER",
                ClubMembership.status == "ACTIVE",
            )
        )
    assert remaining_managers == 1


def test_club_member_list_pagination_and_authorization(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.insert(ClubMembership),
            [
                _membership_row(205, 11, 1, "MEMBER", status="ACTIVE"),
                _membership_row(206, 11, 3, "MEMBER", status="LEFT"),
                _membership_row(207, 11, 4, "MEMBER", status="REMOVED"),
            ],
        )

    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        page_one = service.get_club_members(11, _actor(2), session, page=1, page_size=1)
        page_two = service.get_club_members(11, _actor(2), session, page=2, page_size=1)

    assert page_one.total == 2
    assert page_one.page == 1
    assert page_one.page_size == 1
    assert len(page_one.items) == 1
    assert len(page_two.items) == 1
    returned_user_ids = {page_one.items[0].user_id, page_two.items[0].user_id}
    assert returned_user_ids == {1, 2}
    for item in (*page_one.items, *page_two.items):
        dumped = item.model_dump()
        assert set(dumped) == {
            "membership_id",
            "user_id",
            "full_name",
            "role",
            "status",
            "joined_at",
        }

    with Session(engine) as session, pytest.raises(ClubManagerRequiredError):
        service.get_club_members(11, _actor(1), session)
    with Session(engine) as session, pytest.raises(ClubManagerRequiredError):
        service.get_club_members(11, _actor(3), session)
    with Session(engine) as session, pytest.raises(StudentRoleRequiredError):
        service.get_club_members(11, _actor(99, "ADMIN"), session)


def _assert_single_approved_membership(engine: sa.Engine) -> None:
    with engine.connect() as connection:
        application = connection.execute(sa.select(MembershipApplication)).one()
        member_count = connection.scalar(
            sa.select(sa.func.count())
            .select_from(ClubMembership)
            .where(ClubMembership.user_id == 1)
        )
    assert application.status == "APPROVED"
    assert member_count == 1
