from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.modules.clubs.exceptions import (
    AdminRoleRequiredError,
    ClubRequestAlreadyReviewedError,
    ClubRequestNotFoundError,
    RejectionReasonRequiredError,
    StudentRoleRequiredError,
)
from app.modules.clubs.models import Club, ClubCreationRequest, ClubMembership
from app.modules.clubs.repository import (
    add_approved_club,
    add_club_request,
    find_club_by_request,
    find_club_request,
    list_pending_requests,
    list_student_clubs,
    list_student_requests,
    lock_club_request,
)
from app.modules.clubs.schemas import ClubRequestCreate, ClubRequestResponse, ClubSummary
from app.modules.identity.schemas import CurrentUserResponse


def _timestamp() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _require_student(user: CurrentUserResponse) -> None:
    if user.global_role != "STUDENT":
        raise StudentRoleRequiredError()


def _require_admin(user: CurrentUserResponse) -> None:
    if user.global_role != "ADMIN":
        raise AdminRoleRequiredError()


def _as_utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.replace(tzinfo=UTC)


def _club_summary(club: Club) -> ClubSummary:
    return ClubSummary(
        id=club.id,
        name=club.name,
        category=club.category,
        description=club.description,
        status=club.status,
    )


def _response(session: Session, request: ClubCreationRequest) -> ClubRequestResponse:
    club = find_club_by_request(session, request.id) if request.status == "APPROVED" else None
    return ClubRequestResponse(
        id=request.id,
        requested_by=request.requested_by,
        proposed_name=request.proposed_name,
        category=request.category,
        mission=request.mission,
        initial_plan=request.initial_plan,
        status=request.status,
        reviewed_by=request.reviewed_by,
        reviewed_at=_as_utc(request.reviewed_at),
        rejection_reason=request.rejection_reason,
        created_at=_as_utc(request.created_at),
        updated_at=_as_utc(request.updated_at),
        club=None if club is None else _club_summary(club),
    )


def submit_club_request(
    payload: ClubRequestCreate, user: CurrentUserResponse, session: Session
) -> ClubRequestResponse:
    _require_student(user)
    now = _timestamp()
    request = ClubCreationRequest(
        requested_by=user.id,
        proposed_name=payload.proposed_name,
        category=payload.category,
        mission=payload.mission,
        initial_plan=payload.initial_plan,
        status="PENDING",
        created_at=now,
        updated_at=now,
    )
    if session.in_transaction():
        raise RuntimeError(
            "Club request submission requires a session without an active transaction"
        )
    with session.begin():
        add_club_request(session, request)
    return _response(session, request)


def get_student_request(
    request_id: int, user: CurrentUserResponse, session: Session
) -> ClubRequestResponse:
    _require_student(user)
    request = find_club_request(session, request_id)
    if request is None or request.requested_by != user.id:
        raise ClubRequestNotFoundError()
    return _response(session, request)


def get_student_requests(user: CurrentUserResponse, session: Session) -> list[ClubRequestResponse]:
    _require_student(user)
    return [_response(session, request) for request in list_student_requests(session, user.id)]


def get_pending_requests(user: CurrentUserResponse, session: Session) -> list[ClubRequestResponse]:
    _require_admin(user)
    return [_response(session, request) for request in list_pending_requests(session)]


def approve_club_request(
    request_id: int, user: CurrentUserResponse, session: Session
) -> ClubRequestResponse:
    _require_admin(user)
    if session.in_transaction():
        raise RuntimeError("Club request approval requires a session without an active transaction")
    with session.begin():
        request = lock_club_request(session, request_id)
        if request is None:
            raise ClubRequestNotFoundError()
        if request.status == "APPROVED":
            return _response(session, request)
        if request.status != "PENDING":
            raise ClubRequestAlreadyReviewedError()

        now = _timestamp()
        request.status = "APPROVED"
        request.reviewed_by = user.id
        request.reviewed_at = now
        request.rejection_reason = None
        request.updated_at = now
        club = Club(
            source_request_id=request.id,
            name=request.proposed_name,
            category=request.category,
            description=request.mission,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        membership = ClubMembership(
            user_id=request.requested_by,
            source_application_id=None,
            role="MANAGER",
            status="ACTIVE",
            joined_at=now,
            ended_at=None,
        )
        add_approved_club(session, club, membership)
    return _response(session, request)


def reject_club_request(
    request_id: int,
    rejection_reason: str | None,
    user: CurrentUserResponse,
    session: Session,
) -> ClubRequestResponse:
    _require_admin(user)
    if rejection_reason is None:
        raise RejectionReasonRequiredError()
    if session.in_transaction():
        raise RuntimeError(
            "Club request rejection requires a session without an active transaction"
        )
    with session.begin():
        request = lock_club_request(session, request_id)
        if request is None:
            raise ClubRequestNotFoundError()
        if request.status != "PENDING":
            raise ClubRequestAlreadyReviewedError()
        now = _timestamp()
        request.status = "REJECTED"
        request.reviewed_by = user.id
        request.reviewed_at = now
        request.rejection_reason = rejection_reason
        request.updated_at = now
    return _response(session, request)


def get_my_clubs(user: CurrentUserResponse, session: Session) -> list[ClubSummary]:
    _require_student(user)
    return [_club_summary(club) for club in list_student_clubs(session, user.id)]
