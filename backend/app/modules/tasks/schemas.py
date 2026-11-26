from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _clean_text(value: str, *, field_name: str, maximum: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    if len(cleaned) > maximum:
        raise ValueError(f"{field_name} must not exceed {maximum} characters")
    if any(unicodedata.category(character) == "Cc" for character in cleaned):
        raise ValueError(f"{field_name} must not contain control characters")
    return cleaned


class EventTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str | None = None
    due_at: datetime | None = None
    assignee_membership_id: int | None = Field(default=None, ge=1)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _clean_text(value, field_name="Title", maximum=200)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_text(value, field_name="Description", maximum=10000)


class EventTaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    due_at: datetime | None = None
    assignee_membership_id: int | None = Field(default=None, ge=1)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_text(value, field_name="Title", maximum=200)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_text(value, field_name="Description", maximum=10000)


class EventTaskStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["TODO", "IN_PROGRESS", "DONE"]


class EventTaskResponse(BaseModel):
    id: int
    event_id: int
    event_title: str
    club_id: int
    club_name: str
    assignee_membership_id: int | None
    assignee_name: str | None
    created_by: int
    title: str
    description: str | None
    status: Literal["TODO", "IN_PROGRESS", "DONE"]
    due_at: datetime | None
    version: int
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EventTaskListResponse(BaseModel):
    items: list[EventTaskResponse]
    total: int
    page: int
    page_size: int


class EventTaskProgressResponse(BaseModel):
    event_id: int
    total: int
    todo: int
    in_progress: int
    done: int
    completion_percentage: float
