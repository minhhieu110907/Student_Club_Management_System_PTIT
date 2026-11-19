from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException
from app.modules.clubs.authorization import require_active_manager
from app.modules.clubs.exceptions import ClubNotFoundError, StudentRoleRequiredError
from app.modules.events.exceptions import (
    CancellationDeadlinePassedError,
    DuplicateEventRegistrationError,
    EventCapacityBelowRegistrationsError,
    EventCapacityFullError,
    EventClubNotActiveError,
    EventInvalidStateError,
    EventMembersOnlyError,
    EventNotFoundError,
    EventRegistrationNotFoundError,
    EventRegistrationWindowClosedError,
)
from app.modules.events.models import Event, EventRegistration
from app.modules.events.repository import (
    add_event,
    add_registration,
    cancel_active_registrations_for_event,
    find_active_membership,
    find_active_registration_for_update,
    find_club,
    find_event_with_club,
    list_club_events,
    list_discoverable_events,
    list_event_participants,
    list_user_registrations,
    lock_event,
)
from app.modules.events.schemas import (
    EventCancelRequest,
    EventCreate,
    EventListResponse,
    EventParticipantListResponse,
    EventParticipantSummary,
    EventRegistrationResponse,
    EventResponse,
    EventUpdate,
    MyRegistrationListResponse,
)
from app.modules.identity.schemas import CurrentUserResponse

_MYSQL_DUPLICATE_KEY = 1062
_MYSQL_DUPLICATE_KEY_PATTERN = re.compile(r"\bfor key\s+['`]([^'`]+)['`]", re.IGNORECASE)
_ACTIVE_REGISTRATION_CONSTRAINT = "uq_registration_active"


def _timestamp() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _as_utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.replace(tzinfo=UTC)


def _require_student(user: CurrentUserResponse) -> None:
    if user.global_role != "STUDENT":
        raise StudentRoleRequiredError()


def _require_clean_transaction(session: Session, operation: str) -> None:
    if session.in_transaction():
        raise RuntimeError(f"{operation} requires a session without an active transaction")


def _duplicate_constraint(exc: IntegrityError) -> str | None:
    arguments = getattr(exc.orig, "args", ())
    if len(arguments) < 2 or arguments[0] != _MYSQL_DUPLICATE_KEY:
        return None
    match = _MYSQL_DUPLICATE_KEY_PATTERN.search(str(arguments[1]))
    if match is None:
        return None
    return match.group(1).rsplit(".", maxsplit=1)[-1]


def _event_response(event: Event, club_name: str, *, is_registered: bool = False) -> EventResponse:
    return EventResponse(
        id=event.id,
        club_id=event.club_id,
        club_name=club_name,
        created_by=event.created_by,
        title=event.title,
        description=event.description,
        location=event.location,
        status=event.status,
        visibility=event.visibility,
        starts_at=_as_utc(event.starts_at),
        ends_at=_as_utc(event.ends_at),
        registration_opens_at=_as_utc(event.registration_opens_at),
        registration_closes_at=_as_utc(event.registration_closes_at),
        cancellation_deadline_at=_as_utc(event.cancellation_deadline_at),
        capacity=event.capacity,
        registration_count=event.registration_count,
        is_registered=is_registered,
        version=event.version,
        published_at=_as_utc(event.published_at),
        cancelled_at=_as_utc(event.cancelled_at),
        cancellation_reason=event.cancellation_reason,
        created_at=_as_utc(event.created_at),
        updated_at=_as_utc(event.updated_at),
    )


def _registration_response(
    registration: EventRegistration, event: Event, club_name: str
) -> EventRegistrationResponse:
    return EventRegistrationResponse(
        id=registration.id,
        event_id=event.id,
        event_title=event.title,
        club_id=event.club_id,
        club_name=club_name,
        event_status=event.status,
        event_starts_at=_as_utc(event.starts_at),
        user_id=registration.user_id,
        status=registration.status,
        registered_at=_as_utc(registration.registered_at),
        cancelled_at=_as_utc(registration.cancelled_at),
        cancellation_reason=registration.cancellation_reason,
    )


def create_event(
    club_id: int,
    payload: EventCreate,
    user: CurrentUserResponse,
    session: Session,
) -> EventResponse:
    _require_student(user)
    _require_clean_transaction(session, "Event creation")
    with session.begin():
        require_active_manager(session, club_id, user.id, for_update=False)
        club = find_club(session, club_id)
        if club is None:
            raise ClubNotFoundError()
        if club.status != "ACTIVE":
            raise EventClubNotActiveError()

        now = _timestamp()
        event = Event(
            club_id=club_id,
            created_by=user.id,
            title=payload.title,
            description=payload.description,
            location=payload.location,
            status="DRAFT",
            visibility=payload.visibility,
            starts_at=_to_naive_utc(payload.starts_at),
            ends_at=_to_naive_utc(payload.ends_at),
            registration_opens_at=_to_naive_utc(payload.registration_opens_at),
            registration_closes_at=_to_naive_utc(payload.registration_closes_at),
            cancellation_deadline_at=_to_naive_utc(payload.cancellation_deadline_at),
            capacity=payload.capacity,
            registration_count=0,
            version=0,
            published_at=None,
            cancelled_at=None,
            cancellation_reason=None,
            created_at=now,
            updated_at=now,
        )
        add_event(session, event)
    return _event_response(event, club.name)


def list_events(
    user: CurrentUserResponse,
    session: Session,
    *,
    club_id: int | None = None,
    visibility: str | None = None,
    upcoming_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> EventListResponse:
    rows, total = list_discoverable_events(
        session,
        user_id=user.id,
        club_id=club_id,
        visibility=visibility,
        upcoming_only=upcoming_only,
        now=_timestamp(),
        page=page,
        page_size=page_size,
    )
    return EventListResponse(
        items=[
            _event_response(event, club_name, is_registered=is_registered)
            for event, club_name, is_registered in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


def list_managed_club_events(
    club_id: int,
    user: CurrentUserResponse,
    session: Session,
    *,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> EventListResponse:
    _require_student(user)
    require_active_manager(session, club_id, user.id, for_update=False)
    rows, total = list_club_events(
        session, club_id=club_id, status=status, page=page, page_size=page_size
    )
    return EventListResponse(
        items=[_event_response(event, club_name) for event, club_name in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_event_detail(
    event_id: int,
    user: CurrentUserResponse,
    session: Session,
) -> EventResponse:
    found = find_event_with_club(session, event_id, user_id=user.id)
    if found is None:
        raise EventNotFoundError()
    event, club_name, is_registered = found

    if event.status != "PUBLISHED":
        if user.global_role == "STUDENT":
            require_active_manager(session, event.club_id, user.id, for_update=False)
        else:
            raise EventNotFoundError()
    elif event.visibility == "CLUB_MEMBERS_ONLY" and user.global_role == "STUDENT":
        if find_active_membership(session, event.club_id, user.id) is None:
            raise EventMembersOnlyError()

    return _event_response(event, club_name, is_registered=is_registered)


def update_event(
    event_id: int,
    payload: EventUpdate,
    user: CurrentUserResponse,
    session: Session,
) -> EventResponse:
    _require_student(user)
    _require_clean_transaction(session, "Event update")
    with session.begin():
        event = lock_event(session, event_id)
        if event is None:
            raise EventNotFoundError()
        require_active_manager(session, event.club_id, user.id, for_update=False)
        club = find_club(session, event.club_id)
        if club is None:
            raise ClubNotFoundError()
        if event.status not in {"DRAFT", "PUBLISHED"}:
            raise EventInvalidStateError("Cancelled or completed events cannot be edited")

        if event.status == "PUBLISHED" and any(
            field is not None
            for field in (
                payload.visibility,
                payload.starts_at,
                payload.ends_at,
                payload.registration_opens_at,
            )
        ):
            raise EventInvalidStateError(
                "Visibility, event schedule, and registration start cannot change after publish"
            )

        if payload.capacity is not None and payload.capacity < event.registration_count:
            raise EventCapacityBelowRegistrationsError()

        new_starts_at = (
            event.starts_at if payload.starts_at is None else _to_naive_utc(payload.starts_at)
        )
        new_ends_at = event.ends_at if payload.ends_at is None else _to_naive_utc(payload.ends_at)
        new_reg_opens = (
            event.registration_opens_at
            if payload.registration_opens_at is None
            else _to_naive_utc(payload.registration_opens_at)
        )
        new_reg_closes = (
            event.registration_closes_at
            if payload.registration_closes_at is None
            else _to_naive_utc(payload.registration_closes_at)
        )
        new_cancel_deadline = (
            event.cancellation_deadline_at
            if payload.cancellation_deadline_at is None
            else _to_naive_utc(payload.cancellation_deadline_at)
        )

        if new_ends_at <= new_starts_at:
            raise BadRequestException("ends_at must be after starts_at")
        if new_reg_closes <= new_reg_opens:
            raise BadRequestException("registration_closes_at must be after registration_opens_at")
        if new_reg_closes > new_ends_at:
            raise BadRequestException("registration_closes_at must not be after ends_at")
        if new_cancel_deadline is not None and new_cancel_deadline > new_starts_at:
            raise BadRequestException("cancellation_deadline_at must not be after starts_at")

        if payload.title is not None:
            event.title = payload.title
        if payload.description is not None:
            event.description = payload.description
        if payload.location is not None:
            event.location = payload.location
        if payload.visibility is not None:
            event.visibility = payload.visibility
        if payload.capacity is not None:
            event.capacity = payload.capacity

        event.starts_at = new_starts_at
        event.ends_at = new_ends_at
        event.registration_opens_at = new_reg_opens
        event.registration_closes_at = new_reg_closes
        event.cancellation_deadline_at = new_cancel_deadline
        event.version += 1
        event.updated_at = _timestamp()
        session.flush([event])
    return _event_response(event, club.name)


def publish_event(
    event_id: int,
    user: CurrentUserResponse,
    session: Session,
) -> EventResponse:
    _require_student(user)
    _require_clean_transaction(session, "Event publish")
    with session.begin():
        event = lock_event(session, event_id)
        if event is None:
            raise EventNotFoundError()
        require_active_manager(session, event.club_id, user.id, for_update=False)
        club = find_club(session, event.club_id)
        if club is None:
            raise ClubNotFoundError()
        if club.status != "ACTIVE":
            raise EventClubNotActiveError()
        if event.status != "DRAFT":
            raise EventInvalidStateError("Only draft events can be published")

        now = _timestamp()
        event.status = "PUBLISHED"
        event.published_at = now
        event.version += 1
        event.updated_at = now
        session.flush([event])
    return _event_response(event, club.name)


def cancel_event(
    event_id: int,
    payload: EventCancelRequest,
    user: CurrentUserResponse,
    session: Session,
) -> EventResponse:
    _require_student(user)
    _require_clean_transaction(session, "Event cancellation")
    with session.begin():
        event = lock_event(session, event_id)
        if event is None:
            raise EventNotFoundError()
        require_active_manager(session, event.club_id, user.id, for_update=False)
        club = find_club(session, event.club_id)
        if club is None:
            raise ClubNotFoundError()
        if event.status not in {"DRAFT", "PUBLISHED"}:
            raise EventInvalidStateError("Event is already cancelled or completed")

        now = _timestamp()
        cancel_active_registrations_for_event(
            session,
            event_id=event.id,
            cancelled_at=now,
            reason="Event cancelled by organizer",
        )
        event.status = "CANCELLED"
        event.cancelled_at = now
        event.cancellation_reason = payload.cancellation_reason
        event.registration_count = 0
        event.version += 1
        event.updated_at = now
        session.flush([event])
    return _event_response(event, club.name)


def register_for_event(
    event_id: int,
    user: CurrentUserResponse,
    session: Session,
) -> EventRegistrationResponse:
    _require_student(user)
    _require_clean_transaction(session, "Event registration")
    try:
        with session.begin():
            event = lock_event(session, event_id)
            if event is None:
                raise EventNotFoundError()
            club = find_club(session, event.club_id)
            if club is None or club.status != "ACTIVE":
                raise EventClubNotActiveError()
            if event.status != "PUBLISHED":
                raise EventInvalidStateError("Event is not open for registration")

            now = _timestamp()
            if (
                now < event.registration_opens_at
                or now > event.registration_closes_at
                or now >= event.ends_at
            ):
                raise EventRegistrationWindowClosedError()

            if (
                event.visibility == "CLUB_MEMBERS_ONLY"
                and find_active_membership(session, event.club_id, user.id) is None
            ):
                raise EventMembersOnlyError()

            if find_active_registration_for_update(session, event_id, user.id) is not None:
                raise DuplicateEventRegistrationError()

            if event.registration_count >= event.capacity:
                raise EventCapacityFullError()

            registration = EventRegistration(
                event_id=event.id,
                user_id=user.id,
                status="REGISTERED",
                registered_at=now,
                cancelled_at=None,
                cancellation_reason=None,
            )
            add_registration(session, registration)
            event.registration_count += 1
            event.version += 1
            event.updated_at = now
            session.flush([event])
    except IntegrityError as exc:
        session.rollback()
        if _duplicate_constraint(exc) == _ACTIVE_REGISTRATION_CONSTRAINT:
            raise DuplicateEventRegistrationError() from exc
        raise

    return _registration_response(registration, event, club.name)


def cancel_event_registration(
    event_id: int,
    user: CurrentUserResponse,
    session: Session,
) -> EventRegistrationResponse:
    _require_student(user)
    _require_clean_transaction(session, "Event registration cancellation")
    with session.begin():
        event = lock_event(session, event_id)
        if event is None:
            raise EventNotFoundError()
        club = find_club(session, event.club_id)
        if club is None:
            raise ClubNotFoundError()
        if event.status != "PUBLISHED":
            raise EventInvalidStateError("Cannot cancel registration for this event state")

        now = _timestamp()
        if now >= event.starts_at:
            raise CancellationDeadlinePassedError()
        if event.cancellation_deadline_at is not None and now > event.cancellation_deadline_at:
            raise CancellationDeadlinePassedError()

        registration = find_active_registration_for_update(session, event_id, user.id)
        if registration is None:
            raise EventRegistrationNotFoundError()

        registration.status = "CANCELLED"
        registration.cancelled_at = now
        registration.cancellation_reason = "Cancelled by student"
        event.registration_count -= 1
        event.version += 1
        event.updated_at = now
        session.flush([registration, event])
    return _registration_response(registration, event, club.name)


def get_my_registrations(
    user: CurrentUserResponse,
    session: Session,
    *,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> MyRegistrationListResponse:
    _require_student(user)
    rows, total = list_user_registrations(
        session, user_id=user.id, status=status, page=page, page_size=page_size
    )
    return MyRegistrationListResponse(
        items=[
            _registration_response(registration, event, club_name)
            for registration, event, club_name in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_event_participants(
    event_id: int,
    user: CurrentUserResponse,
    session: Session,
    *,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> EventParticipantListResponse:
    _require_student(user)
    found = find_event_with_club(session, event_id)
    if found is None:
        raise EventNotFoundError()
    event, _club_name, _is_registered = found
    require_active_manager(session, event.club_id, user.id, for_update=False)

    rows, total = list_event_participants(
        session, event_id=event_id, status=status, page=page, page_size=page_size
    )
    return EventParticipantListResponse(
        items=[
            EventParticipantSummary(
                registration_id=registration.id,
                user_id=registration.user_id,
                full_name=full_name,
                status=registration.status,
                registered_at=_as_utc(registration.registered_at),
                cancelled_at=_as_utc(registration.cancelled_at),
            )
            for registration, full_name in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
