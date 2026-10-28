from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.modules.identity.schemas import RegisteredUserResponse, RegistrationRequest
from app.modules.identity.service import register_user

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.post(
    "/register",
    response_model=RegisteredUserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    request: RegistrationRequest,
    session: Annotated[Session, Depends(get_db_session)],
) -> RegisteredUserResponse:
    return register_user(request, session)
