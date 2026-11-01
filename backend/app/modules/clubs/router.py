from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.modules.clubs.schemas import (
    ClubRequestCreate,
    ClubRequestDecision,
    ClubRequestResponse,
    ClubSummary,
)
from app.modules.clubs.service import (
    approve_club_request,
    get_my_clubs,
    get_pending_requests,
    get_student_request,
    get_student_requests,
    reject_club_request,
    submit_club_request,
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
