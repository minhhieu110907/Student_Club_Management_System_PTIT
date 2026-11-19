from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.modules.events.schemas import (
    EventCancelRequest,
    EventCreate,
    EventListResponse,
    EventParticipantListResponse,
    EventRegistrationResponse,
    EventResponse,
    EventUpdate,
    MyRegistrationListResponse,
)
from app.modules.events.service import (
    cancel_event,
    cancel_event_registration,
    create_event,
    get_event_detail,
    get_event_participants,
    get_my_registrations,
    list_events,
    list_managed_club_events,
    publish_event,
    register_for_event,
    update_event,
)
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.schemas import CurrentUserResponse

router = APIRouter(prefix="/api/v1", tags=["events"])
CurrentUser = Annotated[CurrentUserResponse, Depends(get_current_user)]
DatabaseSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/clubs/{club_id}/events", response_model=EventResponse, status_code=status.HTTP_201_CREATED
)
def create_club_event(
    club_id: int,
    payload: EventCreate,
    user: CurrentUser,
    session: DatabaseSession,
) -> EventResponse:
    return create_event(club_id, payload, user, session)


@router.get("/clubs/{club_id}/events", response_model=EventListResponse)
def club_events(
    club_id: int,
    user: CurrentUser,
    session: DatabaseSession,
    status_filter: Literal["DRAFT", "PUBLISHED", "CANCELLED", "COMPLETED"] | None = Query(
        default=None, alias="status"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> EventListResponse:
    return list_managed_club_events(
        club_id, user, session, status=status_filter, page=page, page_size=page_size
    )


@router.get("/events", response_model=EventListResponse)
def discover_events(
    user: CurrentUser,
    session: DatabaseSession,
    club_id: int | None = Query(default=None, ge=1),
    visibility: Literal["PUBLIC_STUDENTS", "CLUB_MEMBERS_ONLY"] | None = Query(default=None),
    upcoming_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> EventListResponse:
    return list_events(
        user,
        session,
        club_id=club_id,
        visibility=visibility,
        upcoming_only=upcoming_only,
        page=page,
        page_size=page_size,
    )


@router.get("/events/{event_id}", response_model=EventResponse)
def event_detail(
    event_id: int,
    user: CurrentUser,
    session: DatabaseSession,
) -> EventResponse:
    return get_event_detail(event_id, user, session)


@router.patch("/events/{event_id}", response_model=EventResponse)
def patch_event(
    event_id: int,
    payload: EventUpdate,
    user: CurrentUser,
    session: DatabaseSession,
) -> EventResponse:
    return update_event(event_id, payload, user, session)


@router.post("/events/{event_id}/publish", response_model=EventResponse)
def publish(
    event_id: int,
    user: CurrentUser,
    session: DatabaseSession,
) -> EventResponse:
    return publish_event(event_id, user, session)


@router.post("/events/{event_id}/cancel", response_model=EventResponse)
def cancel(
    event_id: int,
    payload: EventCancelRequest,
    user: CurrentUser,
    session: DatabaseSession,
) -> EventResponse:
    return cancel_event(event_id, payload, user, session)


@router.post(
    "/events/{event_id}/registrations",
    response_model=EventRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    event_id: int,
    user: CurrentUser,
    session: DatabaseSession,
) -> EventRegistrationResponse:
    return register_for_event(event_id, user, session)


@router.delete("/events/{event_id}/registrations/me", response_model=EventRegistrationResponse)
def cancel_my_registration(
    event_id: int,
    user: CurrentUser,
    session: DatabaseSession,
) -> EventRegistrationResponse:
    return cancel_event_registration(event_id, user, session)


@router.get("/event-registrations/mine", response_model=MyRegistrationListResponse)
def my_registrations(
    user: CurrentUser,
    session: DatabaseSession,
    status_filter: Literal["REGISTERED", "CANCELLED"] | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> MyRegistrationListResponse:
    return get_my_registrations(user, session, status=status_filter, page=page, page_size=page_size)


@router.get("/events/{event_id}/registrations", response_model=EventParticipantListResponse)
def event_participants(
    event_id: int,
    user: CurrentUser,
    session: DatabaseSession,
    status_filter: Literal["REGISTERED", "CANCELLED"] | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> EventParticipantListResponse:
    return get_event_participants(
        event_id, user, session, status=status_filter, page=page, page_size=page_size
    )
