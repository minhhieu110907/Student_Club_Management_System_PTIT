from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.clubs.models import (
    Club,
    ClubCreationRequest,
    ClubMembership,
    MembershipApplication,
)
from app.modules.events.models import Event
from app.modules.identity.models import User
from app.modules.tasks.models import EventTask


def add_club_request(session: Session, request: ClubCreationRequest) -> None:
    session.add(request)
    session.flush([request])


def find_club_request(session: Session, request_id: int) -> ClubCreationRequest | None:
    return session.scalar(select(ClubCreationRequest).where(ClubCreationRequest.id == request_id))


def lock_club_request(session: Session, request_id: int) -> ClubCreationRequest | None:
    return session.scalar(
        select(ClubCreationRequest).where(ClubCreationRequest.id == request_id).with_for_update()
    )


def list_student_requests(session: Session, user_id: int) -> list[ClubCreationRequest]:
    return list(
        session.scalars(
            select(ClubCreationRequest)
            .where(ClubCreationRequest.requested_by == user_id)
            .order_by(ClubCreationRequest.created_at.desc(), ClubCreationRequest.id.desc())
        )
    )


def list_pending_requests(session: Session) -> list[ClubCreationRequest]:
    return list(
        session.scalars(
            select(ClubCreationRequest)
            .where(ClubCreationRequest.status == "PENDING")
            .order_by(ClubCreationRequest.created_at, ClubCreationRequest.id)
        )
    )


def find_club_by_request(session: Session, request_id: int) -> Club | None:
    return session.scalar(select(Club).where(Club.source_request_id == request_id))


def list_student_clubs(session: Session, user_id: int) -> list[Club]:
    return list(
        session.scalars(
            select(Club)
            .join(ClubMembership, ClubMembership.club_id == Club.id)
            .where(
                ClubMembership.user_id == user_id,
                ClubMembership.status == "ACTIVE",
                Club.status == "ACTIVE",
            )
            .order_by(Club.name, Club.id)
        )
    )


def add_approved_club(session: Session, club: Club, membership: ClubMembership) -> None:
    session.add(club)
    session.flush([club])
    membership.club_id = club.id
    session.add(membership)
    session.flush([membership])


def list_active_clubs(session: Session) -> list[Club]:
    return list(
        session.scalars(select(Club).where(Club.status == "ACTIVE").order_by(Club.name, Club.id))
    )


def find_club(session: Session, club_id: int) -> Club | None:
    return session.scalar(select(Club).where(Club.id == club_id))


def lock_club(session: Session, club_id: int) -> Club | None:
    return session.scalar(
        select(Club)
        .where(Club.id == club_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def lock_users(session: Session, user_ids: set[int]) -> list[User]:
    return list(
        session.scalars(
            select(User).where(User.id.in_(sorted(user_ids))).order_by(User.id).with_for_update()
        )
    )


def list_membership_history_for_update(
    session: Session, club_id: int, user_id: int
) -> list[ClubMembership]:
    return list(
        session.scalars(
            select(ClubMembership)
            .where(ClubMembership.club_id == club_id, ClubMembership.user_id == user_id)
            .order_by(ClubMembership.id)
            .with_for_update()
        )
    )


def find_pending_membership_application(
    session: Session, club_id: int, user_id: int
) -> MembershipApplication | None:
    return session.scalar(
        select(MembershipApplication).where(
            MembershipApplication.club_id == club_id,
            MembershipApplication.user_id == user_id,
            MembershipApplication.status == "PENDING",
        )
    )


def add_membership_application(session: Session, application: MembershipApplication) -> None:
    session.add(application)
    session.flush([application])


def find_membership_application(
    session: Session, application_id: int
) -> MembershipApplication | None:
    return session.scalar(
        select(MembershipApplication).where(MembershipApplication.id == application_id)
    )


def lock_membership_application(
    session: Session, application_id: int
) -> MembershipApplication | None:
    return session.scalar(
        select(MembershipApplication)
        .where(MembershipApplication.id == application_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def list_user_membership_applications(
    session: Session, user_id: int
) -> list[MembershipApplication]:
    return list(
        session.scalars(
            select(MembershipApplication)
            .where(MembershipApplication.user_id == user_id)
            .order_by(MembershipApplication.created_at.desc(), MembershipApplication.id.desc())
        )
    )


def list_pending_membership_applications(
    session: Session, club_id: int
) -> list[MembershipApplication]:
    return list(
        session.scalars(
            select(MembershipApplication)
            .where(
                MembershipApplication.club_id == club_id,
                MembershipApplication.status == "PENDING",
            )
            .order_by(MembershipApplication.created_at, MembershipApplication.id)
        )
    )


def find_active_manager_membership_for_update(
    session: Session, club_id: int, user_id: int
) -> ClubMembership | None:
    return session.scalar(
        select(ClubMembership)
        .where(
            ClubMembership.club_id == club_id,
            ClubMembership.user_id == user_id,
            ClubMembership.status == "ACTIVE",
            ClubMembership.role == "MANAGER",
        )
        .with_for_update()
    )


def find_active_manager_membership(
    session: Session, club_id: int, user_id: int
) -> ClubMembership | None:
    return session.scalar(
        select(ClubMembership).where(
            ClubMembership.club_id == club_id,
            ClubMembership.user_id == user_id,
            ClubMembership.status == "ACTIVE",
            ClubMembership.role == "MANAGER",
        )
    )


def add_membership(session: Session, membership: ClubMembership) -> None:
    session.add(membership)
    session.flush([membership])


def list_user_memberships(session: Session, user_id: int) -> list[ClubMembership]:
    return list(
        session.scalars(
            select(ClubMembership)
            .where(ClubMembership.user_id == user_id)
            .order_by(ClubMembership.joined_at.desc(), ClubMembership.id.desc())
        )
    )


def find_membership_club_id(session: Session, membership_id: int, user_id: int) -> int | None:
    return session.scalar(
        select(ClubMembership.club_id).where(
            ClubMembership.id == membership_id,
            ClubMembership.user_id == user_id,
        )
    )


def lock_owned_membership(
    session: Session, membership_id: int, user_id: int
) -> ClubMembership | None:
    return session.scalar(
        select(ClubMembership)
        .where(ClubMembership.id == membership_id, ClubMembership.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def list_active_manager_memberships_for_update(
    session: Session, club_id: int
) -> list[ClubMembership]:
    return list(
        session.scalars(
            select(ClubMembership)
            .where(
                ClubMembership.club_id == club_id,
                ClubMembership.status == "ACTIVE",
                ClubMembership.role == "MANAGER",
            )
            .order_by(ClubMembership.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def list_active_club_members(
    session: Session,
    club_id: int,
    *,
    page: int,
    page_size: int,
) -> tuple[list[tuple[ClubMembership, str]], int]:
    total = session.scalar(
        select(func.count())
        .select_from(ClubMembership)
        .where(ClubMembership.club_id == club_id, ClubMembership.status == "ACTIVE")
    )
    rows = session.execute(
        select(ClubMembership, User.full_name)
        .join(User, User.id == ClubMembership.user_id)
        .where(ClubMembership.club_id == club_id, ClubMembership.status == "ACTIVE")
        .order_by(ClubMembership.joined_at.asc(), ClubMembership.id.asc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    return [(row[0], row[1]) for row in rows], int(total or 0)


def find_users_by_ids(session: Session, user_ids: set[int]) -> dict[int, User]:
    return {
        user.id: user for user in session.scalars(select(User).where(User.id.in_(sorted(user_ids))))
    }


def find_clubs_by_ids(session: Session, club_ids: set[int]) -> dict[int, Club]:
    return {
        club.id: club for club in session.scalars(select(Club).where(Club.id.in_(sorted(club_ids))))
    }


def has_unfinished_assigned_tasks(session: Session, membership_id: int) -> bool:
    row = session.scalar(
        select(EventTask.id)
        .join(Event, Event.id == EventTask.event_id)
        .where(
            EventTask.assignee_membership_id == membership_id,
            EventTask.status.in_(("TODO", "IN_PROGRESS")),
            Event.status.in_(("DRAFT", "PUBLISHED")),
        )
        .limit(1)
        .with_for_update()
    )
    return row is not None
