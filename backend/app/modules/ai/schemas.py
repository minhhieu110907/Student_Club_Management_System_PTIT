from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ListUpcomingEventsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    club_id: int | None = Field(default=None, ge=1)
    visibility: Literal["PUBLIC_STUDENTS", "CLUB_MEMBERS_ONLY"] | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)


class GetMyRegistrationsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["REGISTERED", "CANCELLED"] | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)


class GetMyTasksArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["TODO", "IN_PROGRESS", "DONE"] | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)


class GetEventProgressArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: int = Field(ge=1)


class AIChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = Field(default=None, ge=1)
    club_context_id: int | None = Field(default=None, ge=1)


class AIToolTraceItem(BaseModel):
    tool_name: str
    status: str
    duration_ms: int | None = None


class AIChatResponse(BaseModel):
    conversation_id: int
    turn_id: int
    message_id: int
    provider: str
    model: str
    reply: str
    tool_calls: list[AIToolTraceItem]
    data_retrieved_at: datetime | None = None


class AIMessageItem(BaseModel):
    id: int
    turn_id: int
    role: Literal["USER", "ASSISTANT"]
    status: str
    content: str | None = None
    created_at: datetime


class AIConversationSummary(BaseModel):
    id: int
    title: str | None = None
    club_context_id: int | None = None
    created_at: datetime
    updated_at: datetime


class AIConversationDetailResponse(BaseModel):
    id: int
    title: str | None = None
    club_context_id: int | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[AIMessageItem]


class AIConversationListResponse(BaseModel):
    items: list[AIConversationSummary]
    page: int
    page_size: int
    total: int
