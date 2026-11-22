from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.clubs.authorization import require_active_manager
from app.modules.clubs.exceptions import (
    ActiveAssignedTasksExistError,
    ActiveMembershipExistsError,
    AdminRoleRequiredError,
    ClubNotEligibleError,
    ClubNotFoundError,
    ClubRequestAlreadyReviewedError,
    ClubRequestNotFoundError,
    ManagerLeaveNotAllowedError,
    MembershipApplicationAlreadyReviewedError,
    MembershipApplicationNotFoundError,
    MembershipNotActiveError,
    MembershipNotFoundError,
    PendingMembershipApplicationError,
    RejectionReasonRequiredError,
    RemovedMembershipReapplicationError,
    StudentRoleRequiredError,
)
from app.modules.clubs.models import (
    Club,
    ClubCreationRequest,
    ClubMembership,
    MembershipApplication,
)
from app.modules.clubs.repository import (
    add_approved_club,
    add_club_request,
    add_membership,
    add_membership_application,
    find_club,
    find_club_by_request,
    find_club_request,
    find_clubs_by_ids,
    find_membership_application,
    find_membership_club_id,
    find_pending_membership_application,
    find_users_by_ids,
    has_unfinished_assigned_tasks,
    list_active_club_members,
    list_active_clubs,
    list_active_manager_memberships_for_update,
    list_membership_history_for_update,
    list_pending_membership_applications,
    list_pending_requests,
    list_student_clubs,
    list_student_requests,
    list_user_membership_applications,
    list_user_memberships,
    lock_club,
    lock_club_request,
    lock_membership_application,
    lock_owned_membership,
    lock_users,
)
from app.modules.clubs.schemas import (
    ClubMemberListResponse,
    ClubMemberSummary,
    ClubRequestCreate,
    ClubRequestResponse,
    ClubSummary,
    MembershipApplicantSummary,
    MembershipApplicationCreate,
    MembershipApplicationResponse,
    MembershipResponse,
)
from app.modules.identity.schemas import CurrentUserResponse

_MYSQL_DUPLICATE_KEY = 1062
_MYSQL_DUPLICATE_KEY_PATTERN = re.compile(r"\bfor key\s+['`]([^'`]+)['`]", re.IGNORECASE)
_PENDING_APPLICATION_CONSTRAINT = "uq_membership_pending"
_ACTIVE_MEMBERSHIP_CONSTRAINT = "uq_membership_active"
_SOURCE_APPLICATION_CONSTRAINT = "uq_club_memberships_source_application_id"


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


def get_active_clubs(_user: CurrentUserResponse, session: Session) -> list[ClubSummary]:
    return [_club_summary(club) for club in list_active_clubs(session)]


def _application_response(
    application: MembershipApplication,
    club: Club,
    applicant_name: str,
) -> MembershipApplicationResponse:
    return MembershipApplicationResponse(
        id=application.id,
        club=_club_summary(club),
        applicant=MembershipApplicantSummary(
            id=application.user_id,
            full_name=applicant_name,
        ),
        motivation=application.motivation,
        status=application.status,
        reviewed_by=application.reviewed_by,
        reviewed_at=_as_utc(application.reviewed_at),
        rejection_reason=application.rejection_reason,
        created_at=_as_utc(application.created_at),
    )


def _membership_response(membership: ClubMembership, club: Club) -> MembershipResponse:
    return MembershipResponse(
        id=membership.id,
        club=_club_summary(club),
        source_application_id=membership.source_application_id,
        role=membership.role,
        status=membership.status,
        joined_at=_as_utc(membership.joined_at),
        ended_at=_as_utc(membership.ended_at),
    )


def submit_membership_application(
    club_id: int,
    payload: MembershipApplicationCreate,
    user: CurrentUserResponse,
    session: Session,
) -> MembershipApplicationResponse:
    _require_student(user)
    application = MembershipApplication(
        club_id=club_id,
        user_id=user.id,
        motivation=payload.motivation,
        status="PENDING",
        reviewed_by=None,
        reviewed_at=None,
        rejection_reason=None,
        created_at=_timestamp(),
    )

    try:
        _require_clean_transaction(session, "Membership application submission")
        with session.begin():
            lock_users(session, {user.id})
            club = find_club(session, club_id)
            if club is None:
                raise ClubNotFoundError()
            if club.status != "ACTIVE":
                raise ClubNotEligibleError()

            history = list_membership_history_for_update(session, club_id, user.id)
            if any(membership.status == "ACTIVE" for membership in history):
                raise ActiveMembershipExistsError()
            if any(membership.status == "REMOVED" for membership in history):
                raise RemovedMembershipReapplicationError()
            if find_pending_membership_application(session, club_id, user.id) is not None:
                raise PendingMembershipApplicationError()

            add_membership_application(session, application)
    except IntegrityError as exc:
        session.rollback()
        if _duplicate_constraint(exc) == _PENDING_APPLICATION_CONSTRAINT:
            raise PendingMembershipApplicationError() from exc
        raise

    return _application_response(application, club, user.full_name)


def get_my_membership_applications(
    user: CurrentUserResponse, session: Session
) -> list[MembershipApplicationResponse]:
    _require_student(user)
    applications = list_user_membership_applications(session, user.id)
    clubs = find_clubs_by_ids(session, {item.club_id for item in applications})
    return [
        _application_response(item, clubs[item.club_id], user.full_name) for item in applications
    ]


def get_pending_membership_applications(
    club_id: int, user: CurrentUserResponse, session: Session
) -> list[MembershipApplicationResponse]:
    _require_student(user)
    require_active_manager(session, club_id, user.id, for_update=False)
    applications = list_pending_membership_applications(session, club_id)
    applicants = find_users_by_ids(session, {item.user_id for item in applications})
    club = find_club(session, club_id)
    if club is None:
        raise ClubNotFoundError()
    return [
        _application_response(item, club, applicants[item.user_id].full_name)
        for item in applications
    ]


def approve_membership_application(
    application_id: int, user: CurrentUserResponse, session: Session
) -> MembershipApplicationResponse:
    _require_student(user)
    return _decide_membership_application(
        application_id=application_id,
        rejection_reason=None,
        approve=True,
        user=user,
        session=session,
    )


def reject_membership_application(
    application_id: int,
    rejection_reason: str,
    user: CurrentUserResponse,
    session: Session,
) -> MembershipApplicationResponse:
    _require_student(user)
    return _decide_membership_application(
        application_id=application_id,
        rejection_reason=rejection_reason,
        approve=False,
        user=user,
        session=session,
    )


def _decide_membership_application(
    *,
    application_id: int,
    rejection_reason: str | None,
    approve: bool,
    user: CurrentUserResponse,
    session: Session,
) -> MembershipApplicationResponse:
    try:
        _require_clean_transaction(session, "Membership application decision")
        with session.begin():
            snapshot = find_membership_application(session, application_id)
            if snapshot is None:
                raise MembershipApplicationNotFoundError()

            lock_users(session, {snapshot.user_id, user.id})
            application = lock_membership_application(session, application_id)
            if application is None:
                raise MembershipApplicationNotFoundError()
            require_active_manager(session, application.club_id, user.id, for_update=True)
            if application.status != "PENDING":
                raise MembershipApplicationAlreadyReviewedError()

            club = find_club(session, application.club_id)
            if club is None:
                raise ClubNotFoundError()
            applicant = find_users_by_ids(session, {application.user_id})[application.user_id]
            history = list_membership_history_for_update(
                session, application.club_id, application.user_id
            )
            if any(membership.status == "REMOVED" for membership in history):
                raise RemovedMembershipReapplicationError()

            now = _timestamp()
            application.status = "APPROVED" if approve else "REJECTED"
            application.reviewed_by = user.id
            application.reviewed_at = now
            application.rejection_reason = None if approve else rejection_reason

            if approve:
                if any(membership.status == "ACTIVE" for membership in history):
                    raise ActiveMembershipExistsError()
                add_membership(
                    session,
                    ClubMembership(
                        club_id=application.club_id,
                        user_id=application.user_id,
                        source_application_id=application.id,
                        role="MEMBER",
                        status="ACTIVE",
                        joined_at=now,
                        ended_at=None,
                    ),
                )
            else:
                session.flush([application])
    except IntegrityError as exc:
        session.rollback()
        constraint = _duplicate_constraint(exc)
        if constraint == _ACTIVE_MEMBERSHIP_CONSTRAINT:
            raise ActiveMembershipExistsError() from exc
        if constraint == _SOURCE_APPLICATION_CONSTRAINT:
            raise MembershipApplicationAlreadyReviewedError() from exc
        raise

    return _application_response(application, club, applicant.full_name)


def get_my_memberships(user: CurrentUserResponse, session: Session) -> list[MembershipResponse]:
    _require_student(user)
    memberships = list_user_memberships(session, user.id)
    clubs = find_clubs_by_ids(session, {item.club_id for item in memberships})
    return [_membership_response(item, clubs[item.club_id]) for item in memberships]


def get_club_members(
    club_id: int,
    user: CurrentUserResponse,
    session: Session,
    *,
    page: int = 1,
    page_size: int = 20,
) -> ClubMemberListResponse:
    _require_student(user)
    require_active_manager(session, club_id, user.id, for_update=False)
    club = find_club(session, club_id)
    if club is None:
        raise ClubNotFoundError()
    rows, total = list_active_club_members(session, club_id, page=page, page_size=page_size)
    return ClubMemberListResponse(
        items=[
            ClubMemberSummary(
                membership_id=membership.id,
                user_id=membership.user_id,
                full_name=full_name,
                role=membership.role,
                status="ACTIVE",
                joined_at=_as_utc(membership.joined_at),
            )
            for membership, full_name in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


def leave_membership(
    membership_id: int, user: CurrentUserResponse, session: Session
) -> MembershipResponse:
    _require_student(user)
    _require_clean_transaction(session, "Membership leave")
    with session.begin():
        club_id = find_membership_club_id(session, membership_id, user.id)
        if club_id is None:
            raise MembershipNotFoundError()

        club = lock_club(session, club_id)
        if club is None:
            raise ClubNotFoundError()

        lock_users(session, {user.id})
        membership = lock_owned_membership(session, membership_id, user.id)
        if membership is None:
            raise MembershipNotFoundError()
        if membership.status != "ACTIVE":
            raise MembershipNotActiveError()
        if membership.role == "MANAGER" and club.status == "ACTIVE":
            active_managers = list_active_manager_memberships_for_update(session, club_id)
            if len(active_managers) <= 1:
                raise ManagerLeaveNotAllowedError()
        if has_unfinished_assigned_tasks(session, membership.id):
            raise ActiveAssignedTasksExistError()

        membership.status = "LEFT"
        membership.ended_at = _timestamp()
        session.flush([membership])
    return _membership_response(membership, club)


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
