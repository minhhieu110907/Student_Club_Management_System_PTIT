from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _clean_text(value: str, *, field_name: str, maximum: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    if len(cleaned) > maximum:
        raise ValueError(f"{field_name} must not exceed {maximum} characters")
    if any(unicodedata.category(character) == "Cc" for character in cleaned):
        raise ValueError(f"{field_name} must not contain control characters")
    return cleaned


def _to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


class EventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str
    location: str
    visibility: Literal["PUBLIC_STUDENTS", "CLUB_MEMBERS_ONLY"]
    starts_at: datetime
    ends_at: datetime
    registration_opens_at: datetime
    registration_closes_at: datetime
    cancellation_deadline_at: datetime | None = None
    capacity: int = Field(ge=1, le=100000)

    @model_validator(mode="after")
    def validate_fields_and_windows(self) -> EventCreate:
        self.title = _clean_text(self.title, field_name="Title", maximum=200)
        self.description = _clean_text(self.description, field_name="Description", maximum=10000)
        self.location = _clean_text(self.location, field_name="Location", maximum=255)
        starts_at = _to_naive_utc(self.starts_at)
        ends_at = _to_naive_utc(self.ends_at)
        reg_opens = _to_naive_utc(self.registration_opens_at)
        reg_closes = _to_naive_utc(self.registration_closes_at)
        cancel_deadline = (
            None
            if self.cancellation_deadline_at is None
            else _to_naive_utc(self.cancellation_deadline_at)
        )
        if ends_at <= starts_at:
            raise ValueError("ends_at must be after starts_at")
        if reg_closes <= reg_opens:
            raise ValueError("registration_closes_at must be after registration_opens_at")
        if reg_closes > ends_at:
            raise ValueError("registration_closes_at must not be after ends_at")
        if cancel_deadline is not None and cancel_deadline > starts_at:
            raise ValueError("cancellation_deadline_at must not be after starts_at")
        return self


class EventUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    location: str | None = None
    visibility: Literal["PUBLIC_STUDENTS", "CLUB_MEMBERS_ONLY"] | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None
    cancellation_deadline_at: datetime | None = None
    capacity: int | None = Field(default=None, ge=1, le=100000)

    @model_validator(mode="after")
    def validate_texts(self) -> EventUpdate:
        if self.title is not None:
            self.title = _clean_text(self.title, field_name="Title", maximum=200)
        if self.description is not None:
            self.description = _clean_text(
                self.description, field_name="Description", maximum=10000
            )
        if self.location is not None:
            self.location = _clean_text(self.location, field_name="Location", maximum=255)
        return self


class EventCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cancellation_reason: str

    @model_validator(mode="after")
    def validate_reason(self) -> EventCancelRequest:
        self.cancellation_reason = _clean_text(
            self.cancellation_reason, field_name="Cancellation reason", maximum=1000
        )
        return self


class EventClubSummary(BaseModel):
    id: int
    name: str
    status: Literal["ACTIVE", "SUSPENDED"]


class EventResponse(BaseModel):
    id: int
    club_id: int
    club_name: str
    created_by: int
    title: str
    description: str
    location: str
    status: Literal["DRAFT", "PUBLISHED", "CANCELLED", "COMPLETED"]
    visibility: Literal["PUBLIC_STUDENTS", "CLUB_MEMBERS_ONLY"]
    starts_at: datetime
    ends_at: datetime
    registration_opens_at: datetime
    registration_closes_at: datetime
    cancellation_deadline_at: datetime | None
    capacity: int
    registration_count: int
    is_registered: bool = False
    version: int
    published_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime


class EventListResponse(BaseModel):
    items: list[EventResponse]
    total: int
    page: int
    page_size: int


class EventRegistrationResponse(BaseModel):
    id: int
    event_id: int
    event_title: str
    club_id: int
    club_name: str
    event_status: Literal["DRAFT", "PUBLISHED", "CANCELLED", "COMPLETED"]
    event_starts_at: datetime
    user_id: int
    status: Literal["REGISTERED", "CANCELLED"]
    registered_at: datetime
    cancelled_at: datetime | None
    cancellation_reason: str | None


class MyRegistrationListResponse(BaseModel):
    items: list[EventRegistrationResponse]
    total: int
    page: int
    page_size: int


class EventParticipantSummary(BaseModel):
    registration_id: int
    user_id: int
    full_name: str
    status: Literal["REGISTERED", "CANCELLED"]
    registered_at: datetime
    cancelled_at: datetime | None


class EventParticipantListResponse(BaseModel):
    items: list[EventParticipantSummary]
    total: int
    page: int
    page_size: int
