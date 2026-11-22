import pytest
from pydantic import ValidationError

from app.modules.tasks.schemas import EventTaskCreate, EventTaskStatusUpdate, EventTaskUpdate


def test_task_create_validates_fields_and_forbids_extra() -> None:
    task = EventTaskCreate(
        title="  Prepare slides  ", description="  Deck v1  ", assignee_membership_id=5
    )
    assert task.title == "Prepare slides"
    assert task.description == "Deck v1"
    assert task.assignee_membership_id == 5

    with pytest.raises(ValidationError):
        EventTaskCreate(title="   ")

    with pytest.raises(ValidationError):
        EventTaskCreate(title="Bad\x00Title")

    with pytest.raises(ValidationError):
        EventTaskCreate(title="Valid", assignee_membership_id=0)

    with pytest.raises(ValidationError):
        EventTaskCreate(title="Valid", extra_field="nope")


def test_task_update_and_status_validation() -> None:
    status_update = EventTaskStatusUpdate(status="IN_PROGRESS")
    assert status_update.status == "IN_PROGRESS"

    with pytest.raises(ValidationError):
        EventTaskStatusUpdate(status="BLOCKED")

    with pytest.raises(ValidationError):
        EventTaskUpdate(description="   ")
