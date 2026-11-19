from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.modules.clubs.exceptions import ClubManagerRequiredError
from app.modules.clubs.models import Club, ClubCreationRequest, ClubMembership
from app.modules.events import service
from app.modules.events.exceptions import (
    CancellationDeadlinePassedError,
    DuplicateEventRegistrationError,
    EventCapacityBelowRegistrationsError,
    EventCapacityFullError,
    EventInvalidStateError,
    EventMembersOnlyError,
    EventRegistrationNotFoundError,
    EventRegistrationWindowClosedError,
)
from app.modules.events.models import Event, EventRegistration
from app.modules.events.schemas import EventCancelRequest, EventCreate, EventUpdate
from app.modules.identity.models import User
from app.modules.identity.schemas import CurrentUserResponse

DATABASE_URL = os.getenv("SCMS_EVENTS_INTEGRATION_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="SCMS_EVENTS_INTEGRATION_URL is required"),
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
        users = [
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
            for idx in (*range(1, 16), 99)
        ]
        connection.execute(sa.insert(User), users)
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
                    "club_id": 12,
                    "user_id": 3,
                    "source_application_id": None,
                    "role": "MANAGER",
                    "status": "ACTIVE",
                    "joined_at": now,
                    "ended_at": None,
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
        connection.execute(sa.delete(EventRegistration))
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


def _create_and_publish(
    engine: sa.Engine,
    *,
    visibility: str = "PUBLIC_STUDENTS",
    capacity: int = 5,
    reg_opens_delta: timedelta = timedelta(hours=-1),
    reg_closes_delta: timedelta = timedelta(days=2),
    cancel_deadline_delta: timedelta | None = timedelta(days=1),
    starts_delta: timedelta = timedelta(days=3),
    ends_delta: timedelta = timedelta(days=3, hours=2),
    publish: bool = True,
) -> int:
    now = datetime.now(UTC)
    payload = EventCreate(
        title="SCMS Tech Talk",
        description="Deep dive on backend",
        location="Room 301",
        visibility=visibility,
        starts_at=now + starts_delta,
        ends_at=now + ends_delta,
        registration_opens_at=now + reg_opens_delta,
        registration_closes_at=now + reg_closes_delta,
        cancellation_deadline_at=None
        if cancel_deadline_delta is None
        else now + cancel_deadline_delta,
        capacity=capacity,
    )
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        created = service.create_event(11, payload, _actor(2), session)
    if publish:
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            service.publish_event(created.id, _actor(2), session)
    return created.id


def _assert_count_reconciles(engine: sa.Engine, event_id: int) -> tuple[int, int]:
    with engine.connect() as connection:
        row = connection.execute(
            sa.select(Event.registration_count, Event.capacity).where(Event.id == event_id)
        ).one()
        active = connection.scalar(
            sa.select(sa.func.count())
            .select_from(EventRegistration)
            .where(EventRegistration.event_id == event_id, EventRegistration.status == "REGISTERED")
        )
    assert 0 <= row.registration_count <= row.capacity
    assert row.registration_count == active
    return row.registration_count, row.capacity


def test_event_lifecycle_authorization_visibility_and_deadlines(engine: sa.Engine) -> None:
    draft_id = _create_and_publish(
        engine, visibility="CLUB_MEMBERS_ONLY", capacity=2, publish=False
    )

    # Cross-club manager cannot update, publish, or view draft
    with Session(engine) as session, pytest.raises(ClubManagerRequiredError):
        service.update_event(draft_id, EventUpdate(title="Hacked"), _actor(3), session)
    with Session(engine) as session, pytest.raises(ClubManagerRequiredError):
        service.publish_event(draft_id, _actor(3), session)
    with Session(engine) as session, pytest.raises(ClubManagerRequiredError):
        service.get_event_detail(draft_id, _actor(1), session)

    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        managed = service.list_managed_club_events(11, _actor(2), session)
        assert managed.total == 1
        assert managed.items[0].id == draft_id
        empty_managed = service.list_managed_club_events(12, _actor(3), session)
        assert empty_managed.total == 0
        assert empty_managed.items == []

    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        updated = service.update_event(
            draft_id, EventUpdate(title="Updated Talk"), _actor(2), session
        )
        assert updated.title == "Updated Talk"
        published = service.publish_event(draft_id, _actor(2), session)
        assert published.status == "PUBLISHED"

    # Cannot change visibility after publish
    with Session(engine) as session, pytest.raises(EventInvalidStateError):
        service.update_event(
            draft_id, EventUpdate(visibility="PUBLIC_STUDENTS"), _actor(2), session
        )

    # Non-member cannot register for CLUB_MEMBERS_ONLY
    with Session(engine) as session, pytest.raises(EventMembersOnlyError):
        service.register_for_event(draft_id, _actor(1), session)

    # Active member (user 4) can register
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        reg = service.register_for_event(draft_id, _actor(4), session)
        assert reg.status == "REGISTERED"
        listed = service.list_events(_actor(4), session, page=1, page_size=1)
        assert listed.items[0].id == draft_id
        assert listed.items[0].is_registered is True
        detail = service.get_event_detail(draft_id, _actor(4), session)
        assert detail.is_registered is True
    _assert_count_reconciles(engine, draft_id)

    # Cannot reduce capacity below active registrations (1) -> wait capacity=2, try 0 is Pydantic,
    # add another member or test with 2 registrations -> let's test window & deadline next
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        participants = service.get_event_participants(
            draft_id, _actor(2), session, page=1, page_size=10
        )
        assert participants.total == 1
        assert participants.items[0].user_id == 4
        assert set(participants.items[0].model_dump()) == {
            "registration_id",
            "user_id",
            "full_name",
            "status",
            "registered_at",
            "cancelled_at",
        }

    # Closed registration window rejected
    closed_id = _create_and_publish(
        engine,
        reg_opens_delta=timedelta(hours=2),
        reg_closes_delta=timedelta(hours=5),
        cancel_deadline_delta=timedelta(days=1),
    )
    with Session(engine) as session, pytest.raises(EventRegistrationWindowClosedError):
        service.register_for_event(closed_id, _actor(1), session)

    # Cancellation deadline passed rejected
    past_deadline_id = _create_and_publish(
        engine,
        cancel_deadline_delta=timedelta(minutes=-5),
    )
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        service.register_for_event(past_deadline_id, _actor(1), session)
    with Session(engine) as session, pytest.raises(CancellationDeadlinePassedError):
        service.cancel_event_registration(past_deadline_id, _actor(1), session)


def test_two_users_compete_for_last_seat_exactly_one_succeeds(engine: sa.Engine) -> None:
    event_id = _create_and_publish(engine, capacity=1)
    start = threading.Barrier(2)

    def attempt(user_id: int) -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                service.register_for_event(event_id, _actor(user_id), session)
                return "REGISTERED"
        except EventCapacityFullError:
            return "FULL"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, (1, 4)))

    assert results.count("REGISTERED") == 1
    assert results.count("FULL") == 1
    assert _assert_count_reconciles(engine, event_id) == (1, 1)


def test_many_requests_compete_for_last_seat_never_exceeds_capacity(engine: sa.Engine) -> None:
    event_id = _create_and_publish(engine, capacity=1)
    user_ids = list(range(1, 13))
    start = threading.Barrier(len(user_ids))

    def attempt(user_id: int) -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                service.register_for_event(event_id, _actor(user_id), session)
                return "REGISTERED"
        except EventCapacityFullError:
            return "FULL"

    with ThreadPoolExecutor(max_workers=len(user_ids)) as executor:
        results = list(executor.map(attempt, user_ids))

    assert results.count("REGISTERED") == 1
    assert results.count("FULL") == len(user_ids) - 1
    assert _assert_count_reconciles(engine, event_id) == (1, 1)


def test_concurrent_duplicate_registration_increments_once(engine: sa.Engine) -> None:
    event_id = _create_and_publish(engine, capacity=5)
    start = threading.Barrier(4)

    def attempt(_idx: int) -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                service.register_for_event(event_id, _actor(1), session)
                return "REGISTERED"
        except DuplicateEventRegistrationError:
            return "DUPLICATE"

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(attempt, range(4)))

    assert results.count("REGISTERED") == 1
    assert results.count("DUPLICATE") == 3
    assert _assert_count_reconciles(engine, event_id) == (1, 5)


def test_concurrent_double_cancellation_decrements_once(engine: sa.Engine) -> None:
    event_id = _create_and_publish(engine, capacity=5)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        service.register_for_event(event_id, _actor(1), session)

    start = threading.Barrier(2)

    def cancel(_idx: int) -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                service.cancel_event_registration(event_id, _actor(1), session)
                return "CANCELLED"
        except EventRegistrationNotFoundError:
            return "NOT_FOUND"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(cancel, range(2)))

    assert results.count("CANCELLED") == 1
    assert results.count("NOT_FOUND") == 1
    assert _assert_count_reconciles(engine, event_id) == (0, 5)


def test_concurrent_registration_and_cancellation_reconciles_count(engine: sa.Engine) -> None:
    event_id = _create_and_publish(engine, capacity=1)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        service.register_for_event(event_id, _actor(1), session)

    start = threading.Barrier(2)

    def cancel_existing() -> str:
        start.wait(timeout=10)
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            service.cancel_event_registration(event_id, _actor(1), session)
            return "CANCELLED"

    def register_new() -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                service.register_for_event(event_id, _actor(4), session)
                return "REGISTERED"
        except EventCapacityFullError:
            return "FULL"

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_cancel = executor.submit(cancel_existing)
        f_reg = executor.submit(register_new)
        cancel_res, reg_res = f_cancel.result(), f_reg.result()

    assert cancel_res == "CANCELLED"
    assert reg_res in {"REGISTERED", "FULL"}
    expected_count = 1 if reg_res == "REGISTERED" else 0
    assert _assert_count_reconciles(engine, event_id) == (expected_count, 1)


def test_concurrent_event_cancellation_and_registration_reconciles_count(engine: sa.Engine) -> None:
    event_id = _create_and_publish(engine, capacity=5)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        service.register_for_event(event_id, _actor(1), session)

    start = threading.Barrier(2)

    def manager_cancel() -> str:
        start.wait(timeout=10)
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            service.cancel_event(
                event_id, EventCancelRequest(cancellation_reason="Weather"), _actor(2), session
            )
            return "EVENT_CANCELLED"

    def student_register() -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                service.register_for_event(event_id, _actor(4), session)
                return "REGISTERED"
        except EventInvalidStateError:
            return "INVALID_STATE"

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_mgr = executor.submit(manager_cancel)
        f_stu = executor.submit(student_register)
        assert f_mgr.result() == "EVENT_CANCELLED"
        assert f_stu.result() in {"REGISTERED", "INVALID_STATE"}

    assert _assert_count_reconciles(engine, event_id) == (0, 5)


def test_concurrent_capacity_update_and_registration_preserves_bounds(engine: sa.Engine) -> None:
    event_id = _create_and_publish(engine, capacity=2)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        service.register_for_event(event_id, _actor(1), session)

    start = threading.Barrier(2)

    def reduce_capacity() -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                service.update_event(event_id, EventUpdate(capacity=1), _actor(2), session)
                return "REDUCED"
        except EventCapacityBelowRegistrationsError:
            return "BELOW_REGISTRATIONS"

    def register_second() -> str:
        start.wait(timeout=10)
        try:
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                service.register_for_event(event_id, _actor(4), session)
                return "REGISTERED"
        except EventCapacityFullError:
            return "FULL"

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_cap = executor.submit(reduce_capacity)
        f_reg = executor.submit(register_second)
        cap_res, reg_res = f_cap.result(), f_reg.result()

    if cap_res == "REDUCED":
        assert reg_res == "FULL"
        assert _assert_count_reconciles(engine, event_id) == (1, 1)
    else:
        assert cap_res == "BELOW_REGISTRATIONS"
        assert reg_res == "REGISTERED"
        assert _assert_count_reconciles(engine, event_id) == (2, 2)


def test_injected_failure_mid_registration_rolls_back_atomically(
    engine: sa.Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_id = _create_and_publish(engine, capacity=5)

    original_add = service.add_registration

    def failing_add(session: Session, registration: EventRegistration) -> None:
        original_add(session, registration)
        raise RuntimeError("Simulated failure before event counter update")

    monkeypatch.setattr(service, "add_registration", failing_add)

    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        with pytest.raises(RuntimeError, match="Simulated failure"):
            service.register_for_event(event_id, _actor(1), session)

    assert _assert_count_reconciles(engine, event_id) == (0, 5)
