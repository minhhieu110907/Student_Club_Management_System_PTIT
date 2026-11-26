from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.schemas import CurrentUserResponse
from app.modules.tasks.schemas import (
    EventTaskCreate,
    EventTaskListResponse,
    EventTaskProgressResponse,
    EventTaskResponse,
    EventTaskStatusUpdate,
    EventTaskUpdate,
)
from app.modules.tasks.service import (
    create_event_task,
    get_event_task_progress,
    get_event_tasks,
    get_my_tasks,
    update_event_task,
    update_event_task_status,
)

router = APIRouter(prefix="/api/v1", tags=["tasks"])
CurrentUser = Annotated[CurrentUserResponse, Depends(get_current_user)]
DatabaseSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/events/{event_id}/tasks",
    response_model=EventTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    event_id: int,
    payload: EventTaskCreate,
    user: CurrentUser,
    session: DatabaseSession,
) -> EventTaskResponse:
    return create_event_task(event_id, payload, user, session)


@router.get("/events/{event_id}/tasks", response_model=EventTaskListResponse)
def event_tasks(
    event_id: int,
    user: CurrentUser,
    session: DatabaseSession,
    status_filter: Literal["TODO", "IN_PROGRESS", "DONE"] | None = Query(
        default=None, alias="status"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> EventTaskListResponse:
    return get_event_tasks(
        event_id, user, session, status=status_filter, page=page, page_size=page_size
    )


@router.get("/event-tasks/mine", response_model=EventTaskListResponse)
def my_tasks(
    user: CurrentUser,
    session: DatabaseSession,
    status_filter: Literal["TODO", "IN_PROGRESS", "DONE"] | None = Query(
        default=None, alias="status"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> EventTaskListResponse:
    return get_my_tasks(user, session, status=status_filter, page=page, page_size=page_size)


@router.patch("/event-tasks/{task_id}", response_model=EventTaskResponse)
def patch_task(
    task_id: int,
    payload: EventTaskUpdate,
    user: CurrentUser,
    session: DatabaseSession,
) -> EventTaskResponse:
    return update_event_task(task_id, payload, user, session)


@router.patch("/event-tasks/{task_id}/status", response_model=EventTaskResponse)
def patch_task_status(
    task_id: int,
    payload: EventTaskStatusUpdate,
    user: CurrentUser,
    session: DatabaseSession,
) -> EventTaskResponse:
    return update_event_task_status(task_id, payload, user, session)


@router.get("/events/{event_id}/task-progress", response_model=EventTaskProgressResponse)
def task_progress(
    event_id: int,
    user: CurrentUser,
    session: DatabaseSession,
) -> EventTaskProgressResponse:
    return get_event_task_progress(event_id, user, session)
