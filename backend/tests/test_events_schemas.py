from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.modules.events.schemas import EventCancelRequest, EventCreate, EventUpdate


def _base_payload(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "title": "Robotics Demo Day",
        "description": "Showcase student robotics projects.",
        "location": "Hall A",
        "visibility": "PUBLIC_STUDENTS",
        "starts_at": now + timedelta(days=5),
        "ends_at": now + timedelta(days=5, hours=3),
        "registration_opens_at": now - timedelta(hours=1),
        "registration_closes_at": now + timedelta(days=4),
        "cancellation_deadline_at": now + timedelta(days=3),
        "capacity": 20,
    }
    payload.update(overrides)
    return payload


def test_event_create_validates_windows_and_capacity() -> None:
    event = EventCreate(**_base_payload())
    assert event.title == "Robotics Demo Day"

    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        EventCreate(**_base_payload(ends_at=now + timedelta(days=4)))

    with pytest.raises(ValidationError):
        EventCreate(
            **_base_payload(
                registration_opens_at=now + timedelta(days=4),
                registration_closes_at=now + timedelta(days=3),
            )
        )

    with pytest.raises(ValidationError):
        EventCreate(**_base_payload(cancellation_deadline_at=now + timedelta(days=6)))

    with pytest.raises(ValidationError):
        EventCreate(**_base_payload(capacity=0))

    with pytest.raises(ValidationError):
        EventCreate(**_base_payload(title="   "))

    with pytest.raises(ValidationError):
        EventCreate(**_base_payload(unexpected="field"))


def test_event_update_and_cancel_reject_control_characters_and_empty_reason() -> None:
    with pytest.raises(ValidationError):
        EventUpdate(title="Bad\x00Title")

    with pytest.raises(ValidationError):
        EventCancelRequest(cancellation_reason="   ")
