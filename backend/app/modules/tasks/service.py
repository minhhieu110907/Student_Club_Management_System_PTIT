from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.modules.clubs.authorization import require_active_manager
from app.modules.clubs.exceptions import ClubNotFoundError, StudentRoleRequiredError
from app.modules.clubs.repository import find_active_manager_membership
from app.modules.events.exceptions import EventNotFoundError
from app.modules.identity.schemas import CurrentUserResponse
from app.modules.tasks.exceptions import (
    InvalidTaskAssigneeError,
    TaskAccessDeniedError,
    TaskEventNotEditableError,
    TaskNotFoundError,
)
from app.modules.tasks.models import EventTask
from app.modules.tasks.repository import (
    add_task,
    aggregate_event_task_progress,
    find_active_membership,
    find_assignee_name,
    find_event_club_id,
    find_task_event_and_club,
    find_user_full_name,
    list_event_tasks,
    list_user_assigned_tasks,
    lock_club,
    lock_event,
    lock_membership,
    lock_task,
)
from app.modules.tasks.schemas import (
    EventTaskCreate,
    EventTaskListResponse,
    EventTaskProgressResponse,
    EventTaskResponse,
    EventTaskStatusUpdate,
    EventTaskUpdate,
)

_EDITABLE_EVENT_STATUSES = frozenset({"DRAFT", "PUBLISHED"})


def _timestamp() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _as_utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.replace(tzinfo=UTC)


def _require_student(user: CurrentUserResponse) -> None:
    if user.global_role != "STUDENT":
        raise StudentRoleRequiredError()


def _require_clean_transaction(session: Session, operation: str) -> None:
    if session.in_transaction():
        raise RuntimeError(f"{operation} requires a session without an active transaction")


def _task_response(
    task: EventTask,
    *,
    event_title: str,
    club_name: str,
    assignee_name: str | None,
) -> EventTaskResponse:
    return EventTaskResponse(
        id=task.id,
        event_id=task.event_id,
        event_title=event_title,
        club_id=task.club_id,
        club_name=club_name,
        assignee_membership_id=task.assignee_membership_id,
        assignee_name=assignee_name,
        created_by=task.created_by,
        title=task.title,
        description=task.description,
        status=task.status,
        due_at=_as_utc(task.due_at),
        version=task.version,
        completed_at=_as_utc(task.completed_at),
        created_at=_as_utc(task.created_at),
        updated_at=_as_utc(task.updated_at),
    )


def create_event_task(
    event_id: int,
    payload: EventTaskCreate,
    user: CurrentUserResponse,
    session: Session,
) -> EventTaskResponse:
    _require_student(user)
    _require_clean_transaction(session, "Task creation")
    with session.begin():
        club_id = find_event_club_id(session, event_id)
        if club_id is None:
            raise EventNotFoundError()

        club = lock_club(session, club_id)
        if club is None:
            raise ClubNotFoundError()
        event = lock_event(session, event_id)
        if event is None:
            raise EventNotFoundError()
        require_active_manager(session, club_id, user.id, for_update=False)
        if event.status not in _EDITABLE_EVENT_STATUSES:
            raise TaskEventNotEditableError()

        assignee_name: str | None = None
        if payload.assignee_membership_id is not None:
            assignee = lock_membership(session, payload.assignee_membership_id)
            if assignee is None or assignee.club_id != club_id or assignee.status != "ACTIVE":
                raise InvalidTaskAssigneeError()
            assignee_name = find_user_full_name(session, assignee.user_id)

        now = _timestamp()
        task = EventTask(
            event_id=event.id,
            club_id=club_id,
            assignee_membership_id=payload.assignee_membership_id,
            created_by=user.id,
            title=payload.title,
            description=payload.description,
            status="TODO",
            due_at=_to_naive_utc(payload.due_at),
            version=0,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )
        add_task(session, task)
    return _task_response(
        task, event_title=event.title, club_name=club.name, assignee_name=assignee_name
    )


def get_event_tasks(
    event_id: int,
    user: CurrentUserResponse,
    session: Session,
    *,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> EventTaskListResponse:
    _require_student(user)
    club_id = find_event_club_id(session, event_id)
    if club_id is None:
        raise EventNotFoundError()
    require_active_manager(session, club_id, user.id, for_update=False)
    rows, total = list_event_tasks(
        session, event_id=event_id, status=status, page=page, page_size=page_size
    )
    return EventTaskListResponse(
        items=[
            _task_response(
                task, event_title=event_title, club_name=club_name, assignee_name=assignee_name
            )
            for task, event_title, club_name, assignee_name in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_my_tasks(
    user: CurrentUserResponse,
    session: Session,
    *,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> EventTaskListResponse:
    _require_student(user)
    rows, total = list_user_assigned_tasks(
        session, user_id=user.id, status=status, page=page, page_size=page_size
    )
    return EventTaskListResponse(
        items=[
            _task_response(
                task, event_title=event_title, club_name=club_name, assignee_name=assignee_name
            )
            for task, event_title, club_name, assignee_name in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


def update_event_task(
    task_id: int,
    payload: EventTaskUpdate,
    user: CurrentUserResponse,
    session: Session,
) -> EventTaskResponse:
    _require_student(user)
    _require_clean_transaction(session, "Task update")
    with session.begin():
        meta = find_task_event_and_club(session, task_id)
        if meta is None:
            raise TaskNotFoundError()
        event_id, club_id = meta

        club = lock_club(session, club_id)
        if club is None:
            raise ClubNotFoundError()
        event = lock_event(session, event_id)
        if event is None:
            raise EventNotFoundError()
        require_active_manager(session, club_id, user.id, for_update=False)
        if event.status not in _EDITABLE_EVENT_STATUSES:
            raise TaskEventNotEditableError()

        task = lock_task(session, task_id)
        if task is None:
            raise TaskNotFoundError()

        fields = payload.model_fields_set
        if "assignee_membership_id" in fields:
            if payload.assignee_membership_id is not None:
                assignee = lock_membership(session, payload.assignee_membership_id)
                if assignee is None or assignee.club_id != club_id or assignee.status != "ACTIVE":
                    raise InvalidTaskAssigneeError()
                task.assignee_membership_id = assignee.id
            else:
                task.assignee_membership_id = None

        if "title" in fields and payload.title is not None:
            task.title = payload.title
        if "description" in fields:
            task.description = payload.description
        if "due_at" in fields:
            task.due_at = _to_naive_utc(payload.due_at)

        assignee_name = find_assignee_name(session, task.assignee_membership_id)

        task.version += 1
        task.updated_at = _timestamp()
        session.flush([task])
    return _task_response(
        task, event_title=event.title, club_name=club.name, assignee_name=assignee_name
    )


def update_event_task_status(
    task_id: int,
    payload: EventTaskStatusUpdate,
    user: CurrentUserResponse,
    session: Session,
) -> EventTaskResponse:
    _require_student(user)
    _require_clean_transaction(session, "Task status update")
    with session.begin():
        meta = find_task_event_and_club(session, task_id)
        if meta is None:
            raise TaskNotFoundError()
        event_id, club_id = meta

        club = lock_club(session, club_id)
        if club is None:
            raise ClubNotFoundError()
        event = lock_event(session, event_id)
        if event is None:
            raise EventNotFoundError()
        if event.status not in _EDITABLE_EVENT_STATUSES:
            raise TaskEventNotEditableError()

        task = lock_task(session, task_id)
        if task is None:
            raise TaskNotFoundError()

        is_manager = find_active_manager_membership(session, club_id, user.id) is not None
        if not is_manager:
            my_membership = find_active_membership(session, club_id, user.id)
            if my_membership is None or task.assignee_membership_id != my_membership.id:
                raise TaskAccessDeniedError()

        if payload.status != "DONE" and task.assignee_membership_id is not None:
            assignee = lock_membership(session, task.assignee_membership_id)
            if assignee is None or assignee.club_id != club_id or assignee.status != "ACTIVE":
                raise InvalidTaskAssigneeError()

        now = _timestamp()
        task.status = payload.status
        task.completed_at = now if payload.status == "DONE" else None
        task.version += 1
        task.updated_at = now
        session.flush([task])

        assignee_name = find_assignee_name(session, task.assignee_membership_id)
    return _task_response(
        task, event_title=event.title, club_name=club.name, assignee_name=assignee_name
    )


def get_event_task_progress(
    event_id: int,
    user: CurrentUserResponse,
    session: Session,
) -> EventTaskProgressResponse:
    _require_student(user)
    club_id = find_event_club_id(session, event_id)
    if club_id is None:
        raise EventNotFoundError()
    require_active_manager(session, club_id, user.id, for_update=False)

    total, todo, in_progress, done = aggregate_event_task_progress(session, event_id)
    percentage = 0.0 if total == 0 else round((done / total) * 100, 2)
    return EventTaskProgressResponse(
        event_id=event_id,
        total=total,
        todo=todo,
        in_progress=in_progress,
        done=done,
        completion_percentage=percentage,
    )
