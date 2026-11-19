from __future__ import annotations

from datetime import datetime

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.modules.clubs.models import Club, ClubMembership
from app.modules.events.models import Event, EventRegistration
from app.modules.identity.models import User


def find_club(session: Session, club_id: int) -> Club | None:
    return session.scalar(select(Club).where(Club.id == club_id))


def find_active_membership(session: Session, club_id: int, user_id: int) -> ClubMembership | None:
    return session.scalar(
        select(ClubMembership).where(
            ClubMembership.club_id == club_id,
            ClubMembership.user_id == user_id,
            ClubMembership.status == "ACTIVE",
        )
    )


def add_event(session: Session, event: Event) -> None:
    session.add(event)
    session.flush([event])


def find_event_with_club(
    session: Session, event_id: int, *, user_id: int | None = None
) -> tuple[Event, str, bool] | None:
    is_registered_expr = (
        exists().where(
            EventRegistration.event_id == Event.id,
            EventRegistration.user_id == user_id,
            EventRegistration.status == "REGISTERED",
        )
        if user_id is not None
        else select(False).scalar_subquery()
    )
    row = session.execute(
        select(Event, Club.name, is_registered_expr)
        .join(Club, Club.id == Event.club_id)
        .where(Event.id == event_id)
    ).first()
    if row is None:
        return None
    return row[0], row[1], bool(row[2])


def lock_event(session: Session, event_id: int) -> Event | None:
    return session.scalar(
        select(Event)
        .where(Event.id == event_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def list_discoverable_events(
    session: Session,
    *,
    user_id: int,
    club_id: int | None,
    visibility: str | None,
    upcoming_only: bool,
    now: datetime,
    page: int,
    page_size: int,
) -> tuple[list[tuple[Event, str, bool]], int]:
    active_club_ids = select(ClubMembership.club_id).where(
        ClubMembership.user_id == user_id,
        ClubMembership.status == "ACTIVE",
    )
    filters = [
        Event.status == "PUBLISHED",
        Club.status == "ACTIVE",
        or_(
            Event.visibility == "PUBLIC_STUDENTS",
            Event.club_id.in_(active_club_ids),
        ),
    ]
    if club_id is not None:
        filters.append(Event.club_id == club_id)
    if visibility is not None:
        filters.append(Event.visibility == visibility)
    if upcoming_only:
        filters.append(Event.ends_at >= now)

    total = session.scalar(
        select(func.count()).select_from(Event).join(Club, Club.id == Event.club_id).where(*filters)
    )
    is_registered_expr = exists().where(
        EventRegistration.event_id == Event.id,
        EventRegistration.user_id == user_id,
        EventRegistration.status == "REGISTERED",
    )
    rows = session.execute(
        select(Event, Club.name, is_registered_expr)
        .join(Club, Club.id == Event.club_id)
        .where(*filters)
        .order_by(Event.starts_at.asc(), Event.id.asc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    return [(row[0], row[1], bool(row[2])) for row in rows], int(total or 0)


def list_club_events(
    session: Session,
    *,
    club_id: int,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[tuple[Event, str]], int]:
    filters = [Event.club_id == club_id]
    if status is not None:
        filters.append(Event.status == status)

    total = session.scalar(select(func.count()).select_from(Event).where(*filters))
    rows = session.execute(
        select(Event, Club.name)
        .join(Club, Club.id == Event.club_id)
        .where(*filters)
        .order_by(Event.starts_at.desc(), Event.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    return [(row[0], row[1]) for row in rows], int(total or 0)


def find_active_registration_for_update(
    session: Session, event_id: int, user_id: int
) -> EventRegistration | None:
    return session.scalar(
        select(EventRegistration)
        .where(
            EventRegistration.event_id == event_id,
            EventRegistration.user_id == user_id,
            EventRegistration.status == "REGISTERED",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def add_registration(session: Session, registration: EventRegistration) -> None:
    session.add(registration)
    session.flush([registration])


def cancel_active_registrations_for_event(
    session: Session, *, event_id: int, cancelled_at: datetime, reason: str
) -> int:
    result = session.execute(
        update(EventRegistration)
        .where(
            EventRegistration.event_id == event_id,
            EventRegistration.status == "REGISTERED",
        )
        .values(
            status="CANCELLED",
            cancelled_at=cancelled_at,
            cancellation_reason=reason,
        )
    )
    return int(result.rowcount or 0)


def list_user_registrations(
    session: Session,
    *,
    user_id: int,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[tuple[EventRegistration, Event, str]], int]:
    filters = [EventRegistration.user_id == user_id]
    if status is not None:
        filters.append(EventRegistration.status == status)

    total = session.scalar(select(func.count()).select_from(EventRegistration).where(*filters))
    rows = session.execute(
        select(EventRegistration, Event, Club.name)
        .join(Event, Event.id == EventRegistration.event_id)
        .join(Club, Club.id == Event.club_id)
        .where(*filters)
        .order_by(EventRegistration.registered_at.desc(), EventRegistration.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    return [(row[0], row[1], row[2]) for row in rows], int(total or 0)


def list_event_participants(
    session: Session,
    *,
    event_id: int,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[tuple[EventRegistration, str]], int]:
    filters = [EventRegistration.event_id == event_id]
    if status is not None:
        filters.append(EventRegistration.status == status)

    total = session.scalar(select(func.count()).select_from(EventRegistration).where(*filters))
    rows = session.execute(
        select(EventRegistration, User.full_name)
        .join(User, User.id == EventRegistration.user_id)
        .where(*filters)
        .order_by(EventRegistration.registered_at.asc(), EventRegistration.id.asc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    return [(row[0], row[1]) for row in rows], int(total or 0)
