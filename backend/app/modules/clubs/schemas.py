from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator


def _clean_text(value: str, *, field_name: str, maximum: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    if len(cleaned) > maximum:
        raise ValueError(f"{field_name} must not exceed {maximum} characters")
    if any(unicodedata.category(character) == "Cc" for character in cleaned):
        raise ValueError(f"{field_name} must not contain control characters")
    return cleaned


class ClubRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposed_name: str
    category: str
    mission: str
    initial_plan: str

    @field_validator("proposed_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _clean_text(value, field_name="Proposed name", maximum=160)

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        return _clean_text(value, field_name="Category", maximum=80)

    @field_validator("mission", "initial_plan")
    @classmethod
    def validate_long_text(cls, value: str, info: ValidationInfo) -> str:
        return _clean_text(
            value, field_name=info.field_name.replace("_", " ").title(), maximum=10000
        )


class ClubSummary(BaseModel):
    id: int
    name: str
    category: str
    description: str
    status: Literal["ACTIVE", "SUSPENDED"]


class MembershipApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    motivation: str | None = None

    @field_validator("motivation")
    @classmethod
    def validate_motivation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_text(value, field_name="Motivation", maximum=2000)


class MembershipApplicationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rejection_reason: str

    @field_validator("rejection_reason")
    @classmethod
    def validate_rejection_reason(cls, value: str) -> str:
        return _clean_text(value, field_name="Rejection reason", maximum=1000)


class MembershipApplicantSummary(BaseModel):
    id: int
    full_name: str


class MembershipApplicationResponse(BaseModel):
    id: int
    club: ClubSummary
    applicant: MembershipApplicantSummary
    motivation: str | None
    status: Literal["PENDING", "APPROVED", "REJECTED"]
    reviewed_by: int | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    created_at: datetime


class MembershipResponse(BaseModel):
    id: int
    club: ClubSummary
    source_application_id: int | None
    role: Literal["MEMBER", "MANAGER"]
    status: Literal["ACTIVE", "LEFT", "REMOVED"]
    joined_at: datetime
    ended_at: datetime | None


class ClubMemberSummary(BaseModel):
    membership_id: int
    user_id: int
    full_name: str
    role: Literal["MEMBER", "MANAGER"]
    status: Literal["ACTIVE"]
    joined_at: datetime


class ClubMemberListResponse(BaseModel):
    items: list[ClubMemberSummary]
    total: int
    page: int
    page_size: int


class ClubRequestResponse(BaseModel):
    id: int
    requested_by: int
    proposed_name: str
    category: str
    mission: str
    initial_plan: str
    status: Literal["PENDING", "APPROVED", "REJECTED"]
    reviewed_by: int | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime
    club: ClubSummary | None = None


class ClubRequestDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rejection_reason: str | None = None

    @field_validator("rejection_reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_text(value, field_name="Rejection reason", maximum=1000)
