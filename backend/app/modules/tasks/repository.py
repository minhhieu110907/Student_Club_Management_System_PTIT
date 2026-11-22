from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.modules.clubs.models import Club, ClubMembership
from app.modules.events.models import Event
from app.modules.identity.models import User
from app.modules.tasks.models import EventTask


def find_event_club_id(session: Session, event_id: int) -> int | None:
    return session.scalar(select(Event.club_id).where(Event.id == event_id))


def find_task_event_and_club(session: Session, task_id: int) -> tuple[int, int] | None:
    row = session.execute(
        select(EventTask.event_id, EventTask.club_id).where(EventTask.id == task_id)
    ).first()
    if row is None:
        return None
    return int(row[0]), int(row[1])


def lock_club(session: Session, club_id: int) -> Club | None:
    return session.scalar(
        select(Club)
        .where(Club.id == club_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def lock_event(session: Session, event_id: int) -> Event | None:
    return session.scalar(
        select(Event)
        .where(Event.id == event_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def lock_membership(session: Session, membership_id: int) -> ClubMembership | None:
    return session.scalar(
        select(ClubMembership)
        .where(ClubMembership.id == membership_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def lock_task(session: Session, task_id: int) -> EventTask | None:
    return session.scalar(
        select(EventTask)
        .where(EventTask.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def find_active_membership(session: Session, club_id: int, user_id: int) -> ClubMembership | None:
    return session.scalar(
        select(ClubMembership).where(
            ClubMembership.club_id == club_id,
            ClubMembership.user_id == user_id,
            ClubMembership.status == "ACTIVE",
        )
    )


def find_user_full_name(session: Session, user_id: int) -> str | None:
    return session.scalar(select(User.full_name).where(User.id == user_id))


def find_assignee_name(session: Session, membership_id: int | None) -> str | None:
    if membership_id is None:
        return None
    return session.scalar(
        select(User.full_name)
        .join(ClubMembership, ClubMembership.user_id == User.id)
        .where(ClubMembership.id == membership_id)
    )


def add_task(session: Session, task: EventTask) -> None:
    session.add(task)
    session.flush([task])


def list_event_tasks(
    session: Session,
    *,
    event_id: int,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[tuple[EventTask, str, str, str | None]], int]:
    filters = [EventTask.event_id == event_id]
    if status is not None:
        filters.append(EventTask.status == status)

    total = session.scalar(select(func.count()).select_from(EventTask).where(*filters))
    rows = session.execute(
        select(EventTask, Event.title, Club.name, User.full_name)
        .join(Event, Event.id == EventTask.event_id)
        .join(Club, Club.id == EventTask.club_id)
        .outerjoin(ClubMembership, ClubMembership.id == EventTask.assignee_membership_id)
        .outerjoin(User, User.id == ClubMembership.user_id)
        .where(*filters)
        .order_by(EventTask.id.asc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    return [(row[0], row[1], row[2], row[3]) for row in rows], int(total or 0)


def list_user_assigned_tasks(
    session: Session,
    *,
    user_id: int,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[tuple[EventTask, str, str, str | None]], int]:
    filters = [
        ClubMembership.user_id == user_id,
        ClubMembership.status == "ACTIVE",
    ]
    if status is not None:
        filters.append(EventTask.status == status)

    total = session.scalar(
        select(func.count())
        .select_from(EventTask)
        .join(ClubMembership, ClubMembership.id == EventTask.assignee_membership_id)
        .where(*filters)
    )
    rows = session.execute(
        select(EventTask, Event.title, Club.name, User.full_name)
        .join(Event, Event.id == EventTask.event_id)
        .join(Club, Club.id == EventTask.club_id)
        .join(ClubMembership, ClubMembership.id == EventTask.assignee_membership_id)
        .join(User, User.id == ClubMembership.user_id)
        .where(*filters)
        .order_by(
            case((EventTask.due_at.is_(None), 1), else_=0),
            EventTask.due_at.asc(),
            EventTask.id.asc(),
        )
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    return [(row[0], row[1], row[2], row[3]) for row in rows], int(total or 0)


def aggregate_event_task_progress(session: Session, event_id: int) -> tuple[int, int, int, int]:
    row = session.execute(
        select(
            func.count(EventTask.id),
            func.coalesce(func.sum(case((EventTask.status == "TODO", 1), else_=0)), 0),
            func.coalesce(func.sum(case((EventTask.status == "IN_PROGRESS", 1), else_=0)), 0),
            func.coalesce(func.sum(case((EventTask.status == "DONE", 1), else_=0)), 0),
        ).where(EventTask.event_id == event_id)
    ).one()
    return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0), int(row[3] or 0)
