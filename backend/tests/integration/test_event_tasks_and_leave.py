from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.modules.clubs import repository as club_repository
from app.modules.clubs import service as club_service
from app.modules.clubs.exceptions import (
    ActiveAssignedTasksExistError,
    ClubManagerRequiredError,
    ManagerLeaveNotAllowedError,
)
from app.modules.clubs.models import Club, ClubCreationRequest, ClubMembership
from app.modules.events import service as event_service
from app.modules.events.models import Event
from app.modules.events.schemas import EventCancelRequest, EventCreate
from app.modules.identity.models import User
from app.modules.identity.schemas import CurrentUserResponse
from app.modules.tasks import service as task_service
from app.modules.tasks.exceptions import (
    InvalidTaskAssigneeError,
    TaskAccessDeniedError,
    TaskEventNotEditableError,
)
from app.modules.tasks.models import EventTask
from app.modules.tasks.schemas import EventTaskCreate, EventTaskStatusUpdate, EventTaskUpdate

DATABASE_URL = os.getenv("SCMS_TASKS_INTEGRATION_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="SCMS_TASKS_INTEGRATION_URL is required"),
]


@pytest.fixture
def engine() -> sa.Engine:
    assert DATABASE_URL is not None
    database_engine = sa.create_engine(
        DATABASE_URL, pool_pre_ping=True, pool_size=20, max_overflow=10
    )
    _reset(database_engine)
    now = datetime(2026, 11, 1, 9, 0, 0)
    with database_engine.begin() as connection:
        connection.execute(
            sa.insert(User),
            [
                {
                    "id": idx,
                    "email_normalized": f"user{idx}@example.com",
                    "full_name": f"User {idx}",
                    "password_hash": "hash",
                    "global_role": "ADMIN" if idx == 99 else "STUDENT",
                    "status": "ACTIVE",
                    "created_at": now,
                    "updated_at": now,
                }
                for idx in (1, 2, 3, 4, 5, 99)
            ],
        )
        connection.execute(
            sa.insert(ClubCreationRequest),
            [
                {
                    "id": 1,
                    "requested_by": 2,
                    "proposed_name": "Robotics Club",
                    "category": "Tech",
                    "mission": "Build robots",
                    "initial_plan": "Workshops",
                    "status": "APPROVED",
                    "reviewed_by": 99,
                    "reviewed_at": now,
                    "rejection_reason": None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": 2,
                    "requested_by": 3,
                    "proposed_name": "Design Club",
                    "category": "Arts",
                    "mission": "Design",
                    "initial_plan": "Critiques",
                    "status": "APPROVED",
                    "reviewed_by": 99,
                    "reviewed_at": now,
                    "rejection_reason": None,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
        connection.execute(
            sa.insert(Club),
            [
                {
                    "id": 11,
                    "source_request_id": 1,
                    "name": "Robotics Club",
                    "category": "Tech",
                    "description": "Build robots",
                    "status": "ACTIVE",
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": 12,
                    "source_request_id": 2,
                    "name": "Design Club",
                    "category": "Arts",
                    "description": "Design",
                    "status": "ACTIVE",
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
        connection.execute(
            sa.insert(ClubMembership),
            [
                {
                    "id": 201,
                    "club_id": 11,
                    "user_id": 2,
                    "source_application_id": None,
                    "role": "MANAGER",
                    "status": "ACTIVE",
                    "joined_at": now,
                    "ended_at": None,
                },
                {
                    "id": 202,
                    "club_id": 11,
                    "user_id": 4,
                    "source_application_id": None,
                    "role": "MEMBER",
                    "status": "ACTIVE",
                    "joined_at": now,
                    "ended_at": None,
                },
                {
                    "id": 203,
                    "club_id": 11,
                    "user_id": 5,
                    "source_application_id": None,
                    "role": "MEMBER",
                    "status": "ACTIVE",
                    "joined_at": now,
                    "ended_at": None,
                },
                {
                    "id": 204,
                    "club_id": 12,
                    "user_id": 3,
                    "source_application_id": None,
                    "role": "MANAGER",
                    "status": "ACTIVE",
                    "joined_at": now,
                    "ended_at": None,
                },
                {
                    "id": 205,
                    "club_id": 11,
                    "user_id": 1,
                    "source_application_id": None,
                    "role": "MEMBER",
                    "status": "LEFT",
                    "joined_at": now,
                    "ended_at": now,
                },
            ],
        )
    try:
        yield database_engine
    finally:
        _reset(database_engine)
        database_engine.dispose()


def _reset(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(sa.delete(EventTask))
        connection.execute(sa.delete(Event))
        connection.execute(sa.delete(ClubMembership))
        connection.execute(sa.delete(Club))
        connection.execute(sa.delete(ClubCreationRequest))
        connection.execute(sa.delete(User))


def _actor(user_id: int, role: str = "STUDENT") -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user_id,
        email=f"user{user_id}@example.com",
        full_name=f"User {user_id}",
        global_role=role,
        status="ACTIVE",
    )


def _create_event(engine: sa.Engine) -> int:
    now = datetime.now(UTC)
    payload = EventCreate(
        title="Robotics Expo",
        description="Annual expo",
        location="Main Hall",
        visibility="PUBLIC_STUDENTS",
        starts_at=now + timedelta(days=3),
        ends_at=now + timedelta(days=3, hours=3),
        registration_opens_at=now - timedelta(hours=1),
        registration_closes_at=now + timedelta(days=2),
        cancellation_deadline_at=now + timedelta(days=1),
        capacity=50,
    )
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        return event_service.create_event(11, payload, _actor(2), session).id


def test_task_lifecycle_authorization_completion_and_progress(engine: sa.Engine) -> None:
    event_id = _create_event(engine)

    # Empty progress -> 0.0%
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        empty_prog = task_service.get_event_task_progress(event_id, _actor(2), session)
        assert empty_prog.total == 0
        assert empty_prog.completion_percentage == 0.0

    # Cross-club assignee (204 belongs to club 12) and inactive membership (205 is LEFT) denied
    with Session(engine) as session, pytest.raises(InvalidTaskAssigneeError):
        task_service.create_event_task(
            event_id,
            EventTaskCreate(title="Cross club", assignee_membership_id=204),
            _actor(2),
            session,
        )
    with Session(engine) as session, pytest.raises(InvalidTaskAssigneeError):
        task_service.create_event_task(
            event_id,
            EventTaskCreate(title="Left member", assignee_membership_id=205),
            _actor(2),
            session,
        )
    # Cross-club manager cannot create/list/view progress
    with Session(engine) as session, pytest.raises(ClubManagerRequiredError):
        task_service.create_event_task(
            event_id, EventTaskCreate(title="Unauthorized"), _actor(3), session
        )
    with Session(engine) as session, pytest.raises(ClubManagerRequiredError):
        task_service.get_event_tasks(event_id, _actor(4), session)

    # Manager creates 2 tasks (one assigned to 202, one unassigned)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        t1 = task_service.create_event_task(
            event_id,
            EventTaskCreate(title="Setup booths", assignee_membership_id=202),
            _actor(2),
            session,
        )
        t2 = task_service.create_event_task(
            event_id,
            EventTaskCreate(title="Check audio"),
            _actor(2),
            session,
        )
        assert t1.status == "TODO" and t1.completed_at is None
        assert t2.assignee_membership_id is None

    # Another member (user 5) cannot update t1 status; assigned member (user 4) can
    with Session(engine) as session, pytest.raises(TaskAccessDeniedError):
        task_service.update_event_task_status(
            t1.id, EventTaskStatusUpdate(status="DONE"), _actor(5), session
        )
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        done = task_service.update_event_task_status(
            t1.id, EventTaskStatusUpdate(status="DONE"), _actor(4), session
        )
        assert done.status == "DONE" and done.completed_at is not None and done.version == 1
        reopened = task_service.update_event_task_status(
            t1.id, EventTaskStatusUpdate(status="IN_PROGRESS"), _actor(4), session
        )
        assert (
            reopened.status == "IN_PROGRESS"
            and reopened.completed_at is None
            and reopened.version == 2
        )

    # Member 4 cannot leave while t1 is IN_PROGRESS
    with Session(engine) as session, pytest.raises(ActiveAssignedTasksExistError):
        club_service.leave_membership(202, _actor(4), session)

    # Reassign t1 to member 5 (203) -> now member 4 CAN leave; progress checks
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        reassigned = task_service.update_event_task(
            t1.id, EventTaskUpdate(assignee_membership_id=203), _actor(2), session
        )
        assert reassigned.assignee_membership_id == 203
        task_service.update_event_task_status(
            t2.id, EventTaskStatusUpdate(status="DONE"), _actor(2), session
        )
        prog = task_service.get_event_task_progress(event_id, _actor(2), session)
        assert (prog.total, prog.todo, prog.in_progress, prog.done) == (2, 0, 1, 1)
        assert prog.completion_percentage == 50.0
        my_tasks = task_service.get_my_tasks(_actor(5), session, page=1, page_size=10)
        assert my_tasks.total == 1 and my_tasks.items[0].id == t1.id

    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        assert club_service.leave_membership(202, _actor(4), session).status == "LEFT"

    # Cancelled event blocks task creation/edits
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        event_service.cancel_event(
            event_id, EventCancelRequest(cancellation_reason="Rain"), _actor(2), session
        )
    with Session(engine) as session, pytest.raises(TaskEventNotEditableError):
        task_service.create_event_task(
            event_id, EventTaskCreate(title="Too late"), _actor(2), session
        )


def test_concurrent_task_assignment_and_leave_race(engine: sa.Engine) -> None:
    event_id = _create_event(engine)
    start = threading.Barrier(2)

    def assign() -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                task_service.create_event_task(
                    event_id,
                    EventTaskCreate(title="Race task", assignee_membership_id=202),
                    _actor(2),
                    session,
                )
                return "ASSIGNED"
        except InvalidTaskAssigneeError:
            return "INACTIVE_ASSIGNEE"

    def leave() -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                club_service.leave_membership(202, _actor(4), session)
                return "LEFT"
        except ActiveAssignedTasksExistError:
            return "BLOCKED_BY_TASK"

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_assign = executor.submit(assign)
        f_leave = executor.submit(leave)
        assign_res, leave_res = f_assign.result(), f_leave.result()

    # Either (ASSIGNED + BLOCKED_BY_TASK) or (INACTIVE_ASSIGNEE + LEFT)
    assert (assign_res, leave_res) in {
        ("ASSIGNED", "BLOCKED_BY_TASK"),
        ("INACTIVE_ASSIGNEE", "LEFT"),
    }
    with engine.connect() as connection:
        m_status = connection.scalar(
            sa.select(ClubMembership.status).where(ClubMembership.id == 202)
        )
        task_count = connection.scalar(
            sa.select(sa.func.count())
            .select_from(EventTask)
            .where(EventTask.assignee_membership_id == 202)
        )
    if leave_res == "LEFT":
        assert m_status == "LEFT" and task_count == 0
    else:
        assert m_status == "ACTIVE" and task_count == 1


def test_concurrent_task_reassignment_and_leave_race(engine: sa.Engine) -> None:
    event_id = _create_event(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        task = task_service.create_event_task(
            event_id,
            EventTaskCreate(title="Unassigned initially"),
            _actor(2),
            session,
        )

    start = threading.Barrier(2)

    def reassign() -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                task_service.update_event_task(
                    task.id,
                    EventTaskUpdate(assignee_membership_id=202),
                    _actor(2),
                    session,
                )
                return "REASSIGNED"
        except InvalidTaskAssigneeError:
            return "INACTIVE_ASSIGNEE"

    def leave() -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                club_service.leave_membership(202, _actor(4), session)
                return "LEFT"
        except ActiveAssignedTasksExistError:
            return "BLOCKED_BY_TASK"

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_reassign = executor.submit(reassign)
        f_leave = executor.submit(leave)
        r_res, l_res = f_reassign.result(), f_leave.result()

    assert (r_res, l_res) in {
        ("REASSIGNED", "BLOCKED_BY_TASK"),
        ("INACTIVE_ASSIGNEE", "LEFT"),
    }


def test_injected_failure_mid_task_creation_rolls_back(
    engine: sa.Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_id = _create_event(engine)
    original_add = task_service.add_task

    def failing_add(session: Session, task: EventTask) -> None:
        original_add(session, task)
        raise RuntimeError("Simulated mid-transaction failure")

    monkeypatch.setattr(task_service, "add_task", failing_add)

    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        with pytest.raises(RuntimeError, match="Simulated mid-transaction failure"):
            task_service.create_event_task(
                event_id,
                EventTaskCreate(title="Should rollback", assignee_membership_id=202),
                _actor(2),
                session,
            )

    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(EventTask)) == 0


def test_concurrent_manager_leave_with_tasks_preserves_manager_invariant(engine: sa.Engine) -> None:
    event_id = _create_event(engine)
    # Add second active manager (user 1 -> id 206) and assign an unfinished task to manager 201
    with engine.begin() as connection:
        connection.execute(
            sa.insert(ClubMembership),
            {
                "id": 206,
                "club_id": 11,
                "user_id": 1,
                "source_application_id": None,
                "role": "MANAGER",
                "status": "ACTIVE",
                "joined_at": datetime(2026, 11, 1, 9, 0, 0),
                "ended_at": None,
            },
        )
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        task_service.create_event_task(
            event_id,
            EventTaskCreate(title="Manager task", assignee_membership_id=201),
            _actor(2),
            session,
        )

    # Manager 201 has an unfinished task -> blocked by ActiveAssignedTasksExistError
    with Session(engine) as session, pytest.raises(ActiveAssignedTasksExistError):
        club_service.leave_membership(201, _actor(2), session)

    # Manager 206 has no tasks, CAN leave; then 201 would still be final manager AND has task
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        assert club_service.leave_membership(206, _actor(1), session).status == "LEFT"
    with Session(engine) as session, pytest.raises(ManagerLeaveNotAllowedError):
        club_service.leave_membership(201, _actor(2), session)


def test_leave_policy_respects_event_status_and_task_completion(engine: sa.Engine) -> None:
    # 1. PUBLISHED + TODO -> leave 409 (ActiveAssignedTasksExistError)
    pub_event_id = _create_event(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        event_service.publish_event(pub_event_id, _actor(2), session)
        pub_task = task_service.create_event_task(
            pub_event_id,
            EventTaskCreate(title="Active event task", assignee_membership_id=202),
            _actor(2),
            session,
        )
    with Session(engine) as session, pytest.raises(ActiveAssignedTasksExistError):
        club_service.leave_membership(202, _actor(4), session)

    # 2. PUBLISHED + DONE -> leave succeeds
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        task_service.update_event_task_status(
            pub_task.id, EventTaskStatusUpdate(status="DONE"), _actor(4), session
        )
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        assert club_service.leave_membership(202, _actor(4), session).status == "LEFT"

    # 3. CANCELLED + TODO -> leave succeeds and preserves historical task
    cancel_event_id = _create_event(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        cancel_task = task_service.create_event_task(
            cancel_event_id,
            EventTaskCreate(title="Cancelled event task", assignee_membership_id=203),
            _actor(2),
            session,
        )
        event_service.cancel_event(
            cancel_event_id,
            EventCancelRequest(cancellation_reason="Cancelled"),
            _actor(2),
            session,
        )
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        assert club_service.leave_membership(203, _actor(5), session).status == "LEFT"

    # 4. COMPLETED + IN_PROGRESS -> leave succeeds and preserves historical task
    comp_event_id = _create_event(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        comp_task = task_service.create_event_task(
            comp_event_id,
            EventTaskCreate(title="Completed event task", assignee_membership_id=201),
            _actor(2),
            session,
        )
        task_service.update_event_task_status(
            comp_task.id, EventTaskStatusUpdate(status="IN_PROGRESS"), _actor(2), session
        )
    with engine.begin() as connection:
        connection.execute(
            sa.update(Event).where(Event.id == comp_event_id).values(status="COMPLETED")
        )
        connection.execute(
            sa.insert(ClubMembership),
            {
                "id": 207,
                "club_id": 11,
                "user_id": 1,
                "source_application_id": None,
                "role": "MANAGER",
                "status": "ACTIVE",
                "joined_at": datetime(2026, 11, 1, 9, 0, 0),
                "ended_at": None,
            },
        )
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        assert club_service.leave_membership(201, _actor(2), session).status == "LEFT"

    with engine.connect() as connection:
        assert (
            connection.scalar(sa.select(EventTask.status).where(EventTask.id == cancel_task.id))
            == "TODO"
        )
        assert (
            connection.scalar(sa.select(EventTask.status).where(EventTask.id == comp_task.id))
            == "IN_PROGRESS"
        )


def test_manager_cannot_reopen_task_after_assignee_left(engine: sa.Engine) -> None:
    event_id = _create_event(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        task = task_service.create_event_task(
            event_id,
            EventTaskCreate(title="Done before leave", assignee_membership_id=202),
            _actor(2),
            session,
        )
        task_service.update_event_task_status(
            task.id, EventTaskStatusUpdate(status="DONE"), _actor(4), session
        )
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        assert club_service.leave_membership(202, _actor(4), session).status == "LEFT"

    with Session(engine) as session, pytest.raises(InvalidTaskAssigneeError):
        task_service.update_event_task_status(
            task.id, EventTaskStatusUpdate(status="TODO"), _actor(2), session
        )

    with engine.connect() as connection:
        assert (
            connection.scalar(sa.select(EventTask.status).where(EventTask.id == task.id)) == "DONE"
        )


def test_concurrent_reopen_task_and_leave_race(engine: sa.Engine) -> None:
    event_id = _create_event(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        task = task_service.create_event_task(
            event_id,
            EventTaskCreate(title="Reopen race", assignee_membership_id=202),
            _actor(2),
            session,
        )
        task_service.update_event_task_status(
            task.id, EventTaskStatusUpdate(status="DONE"), _actor(4), session
        )

    start = threading.Barrier(2)

    def reopen() -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                task_service.update_event_task_status(
                    task.id, EventTaskStatusUpdate(status="TODO"), _actor(2), session
                )
                return "REOPENED"
        except InvalidTaskAssigneeError:
            return "INACTIVE_ASSIGNEE"

    def leave() -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                club_service.leave_membership(202, _actor(4), session)
                return "LEFT"
        except ActiveAssignedTasksExistError:
            return "BLOCKED_BY_TASK"

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_reopen = executor.submit(reopen)
        f_leave = executor.submit(leave)
        r_res, l_res = f_reopen.result(), f_leave.result()

    assert (r_res, l_res) in {
        ("REOPENED", "BLOCKED_BY_TASK"),
        ("INACTIVE_ASSIGNEE", "LEFT"),
    }
    with engine.connect() as connection:
        m_status = connection.scalar(
            sa.select(ClubMembership.status).where(ClubMembership.id == 202)
        )
        t_status = connection.scalar(sa.select(EventTask.status).where(EventTask.id == task.id))
    assert not (m_status == "LEFT" and t_status in {"TODO", "IN_PROGRESS"})


def test_concurrent_mark_done_and_leave_race(engine: sa.Engine) -> None:
    event_id = _create_event(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        task = task_service.create_event_task(
            event_id,
            EventTaskCreate(title="Mark done race", assignee_membership_id=202),
            _actor(2),
            session,
        )

    start = threading.Barrier(2)

    def mark_done() -> str:
        start.wait(timeout=10)
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            task_service.update_event_task_status(
                task.id, EventTaskStatusUpdate(status="DONE"), _actor(4), session
            )
            return "DONE"

    def leave() -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                club_service.leave_membership(202, _actor(4), session)
                return "LEFT"
        except ActiveAssignedTasksExistError:
            return "BLOCKED_BY_TASK"

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_done = executor.submit(mark_done)
        f_leave = executor.submit(leave)
        d_res, l_res = f_done.result(), f_leave.result()

    assert d_res == "DONE"
    assert l_res in {"LEFT", "BLOCKED_BY_TASK"}
    with engine.connect() as connection:
        t_status = connection.scalar(sa.select(EventTask.status).where(EventTask.id == task.id))
        m_status = connection.scalar(
            sa.select(ClubMembership.status).where(ClubMembership.id == 202)
        )
    assert t_status == "DONE"
    assert m_status in {"ACTIVE", "LEFT"}


def test_leave_membership_sees_task_committed_after_snapshot_creation(engine: sa.Engine) -> None:
    event_id = _create_event(engine)

    # 1. Session A establishes an InnoDB REPEATABLE READ MVCC snapshot via non-locking SELECT
    with Session(engine, autoflush=False, expire_on_commit=False) as session_a:
        with session_a.begin():
            club_id = club_repository.find_membership_club_id(session_a, 202, 4)
            assert club_id == 11

            # 2. Session B creates & commits a TODO task AFTER Session A's snapshot was fixed
            with Session(engine, autoflush=False, expire_on_commit=False) as session_b:
                task_service.create_event_task(
                    event_id,
                    EventTaskCreate(title="Committed after snapshot", assignee_membership_id=202),
                    _actor(2),
                    session_b,
                )

            # Confirm Session A's non-locking consistent read still sees 0 tasks (stale snapshot)
            stale_count = session_a.scalar(
                sa.select(sa.func.count())
                .select_from(EventTask)
                .where(EventTask.assignee_membership_id == 202)
            )
            assert stale_count == 0

            # 3-4. Locking current read in has_unfinished_assigned_tasks() sees Session B's task
            assert club_repository.has_unfinished_assigned_tasks(session_a, 202) is True

    # 5. leave_membership() rejects leaving and keeps membership ACTIVE
    with Session(engine) as session, pytest.raises(ActiveAssignedTasksExistError):
        club_service.leave_membership(202, _actor(4), session)

    with engine.connect() as connection:
        assert (
            connection.scalar(sa.select(ClubMembership.status).where(ClubMembership.id == 202))
            == "ACTIVE"
        )


def test_leave_membership_end_to_end_sees_task_committed_after_snapshot(
    engine: sa.Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_id = _create_event(engine)
    snapshot_ready = threading.Event()
    task_committed = threading.Event()
    original_lock_club = club_service.lock_club

    def paused_lock_club(session: Session, club_id: int) -> Club | None:
        snapshot_ready.set()
        assert task_committed.wait(timeout=10)
        return original_lock_club(session, club_id)

    monkeypatch.setattr(club_service, "lock_club", paused_lock_club)

    def create_task_in_session_b() -> None:
        assert snapshot_ready.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session_b:
                task_service.create_event_task(
                    event_id,
                    EventTaskCreate(title="E2E after snapshot", assignee_membership_id=202),
                    _actor(2),
                    session_b,
                )
        finally:
            task_committed.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future_b = executor.submit(create_task_in_session_b)
        with Session(engine, autoflush=False, expire_on_commit=False) as session_a:
            with pytest.raises(ActiveAssignedTasksExistError):
                club_service.leave_membership(202, _actor(4), session_a)
        future_b.result()

    with engine.connect() as connection:
        assert (
            connection.scalar(sa.select(ClubMembership.status).where(ClubMembership.id == 202))
            == "ACTIVE"
        )
