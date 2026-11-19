from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.modules.clubs.schemas import (
    ClubMemberListResponse,
    ClubRequestCreate,
    ClubRequestDecision,
    ClubRequestResponse,
    ClubSummary,
    MembershipApplicationCreate,
    MembershipApplicationDecision,
    MembershipApplicationResponse,
    MembershipResponse,
)
from app.modules.clubs.service import (
    approve_club_request,
    approve_membership_application,
    get_active_clubs,
    get_club_members,
    get_my_clubs,
    get_my_membership_applications,
    get_my_memberships,
    get_pending_membership_applications,
    get_pending_requests,
    get_student_request,
    get_student_requests,
    leave_membership,
    reject_club_request,
    reject_membership_application,
    submit_club_request,
    submit_membership_application,
)
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.schemas import CurrentUserResponse

router = APIRouter(prefix="/api/v1", tags=["clubs"])
CurrentUser = Annotated[CurrentUserResponse, Depends(get_current_user)]
DatabaseSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/club-requests", response_model=ClubRequestResponse, status_code=status.HTTP_201_CREATED
)
def submit(payload: ClubRequestCreate, user: CurrentUser, session: DatabaseSession):
    return submit_club_request(payload, user, session)


@router.get("/club-requests/mine", response_model=list[ClubRequestResponse])
def mine(user: CurrentUser, session: DatabaseSession):
    return get_student_requests(user, session)


@router.get("/club-requests/{request_id}", response_model=ClubRequestResponse)
def detail(request_id: int, user: CurrentUser, session: DatabaseSession):
    return get_student_request(request_id, user, session)


@router.get("/clubs/mine", response_model=list[ClubSummary])
def my_clubs(user: CurrentUser, session: DatabaseSession):
    return get_my_clubs(user, session)


@router.get("/clubs", response_model=list[ClubSummary])
def active_clubs(user: CurrentUser, session: DatabaseSession):
    return get_active_clubs(user, session)


@router.get("/clubs/{club_id}/members", response_model=ClubMemberListResponse)
def club_members(
    club_id: int,
    user: CurrentUser,
    session: DatabaseSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return get_club_members(club_id, user, session, page=page, page_size=page_size)


@router.post(
    "/clubs/{club_id}/membership-applications",
    response_model=MembershipApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
def apply_for_membership(
    club_id: int,
    payload: MembershipApplicationCreate,
    user: CurrentUser,
    session: DatabaseSession,
):
    return submit_membership_application(club_id, payload, user, session)


@router.get(
    "/membership-applications/mine",
    response_model=list[MembershipApplicationResponse],
)
def my_membership_applications(user: CurrentUser, session: DatabaseSession):
    return get_my_membership_applications(user, session)


@router.get("/memberships/mine", response_model=list[MembershipResponse])
def my_memberships(user: CurrentUser, session: DatabaseSession):
    return get_my_memberships(user, session)


@router.get(
    "/clubs/{club_id}/membership-applications/pending",
    response_model=list[MembershipApplicationResponse],
)
def pending_membership_applications(club_id: int, user: CurrentUser, session: DatabaseSession):
    return get_pending_membership_applications(club_id, user, session)


@router.post(
    "/membership-applications/{application_id}/approve",
    response_model=MembershipApplicationResponse,
)
def approve_membership(application_id: int, user: CurrentUser, session: DatabaseSession):
    return approve_membership_application(application_id, user, session)


@router.post(
    "/membership-applications/{application_id}/reject",
    response_model=MembershipApplicationResponse,
)
def reject_membership(
    application_id: int,
    decision: MembershipApplicationDecision,
    user: CurrentUser,
    session: DatabaseSession,
):
    return reject_membership_application(application_id, decision.rejection_reason, user, session)


@router.post("/memberships/{membership_id}/leave", response_model=MembershipResponse)
def leave_club(membership_id: int, user: CurrentUser, session: DatabaseSession):
    return leave_membership(membership_id, user, session)


@router.get("/admin/club-requests/pending", response_model=list[ClubRequestResponse])
def pending(user: CurrentUser, session: DatabaseSession):
    return get_pending_requests(user, session)


@router.post("/admin/club-requests/{request_id}/approve", response_model=ClubRequestResponse)
def approve(request_id: int, user: CurrentUser, session: DatabaseSession):
    return approve_club_request(request_id, user, session)


@router.post("/admin/club-requests/{request_id}/reject", response_model=ClubRequestResponse)
def reject(
    request_id: int,
    decision: ClubRequestDecision,
    user: CurrentUser,
    session: DatabaseSession,
):
    return reject_club_request(request_id, decision.rejection_reason, user, session)
