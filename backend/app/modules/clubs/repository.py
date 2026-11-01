from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.clubs.models import Club, ClubCreationRequest, ClubMembership


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
