from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.core.security.password import MAX_PASSWORD_BYTES

MIN_PASSWORD_CODE_POINTS = 10
MAX_EMAIL_CHARACTERS = 254
MAX_FULL_NAME_CHARACTERS = 160


def normalize_email(email: EmailStr) -> str:
    normalized = str(email).casefold()
    if len(normalized) > MAX_EMAIL_CHARACTERS:
        raise ValueError(f"Email must not exceed {MAX_EMAIL_CHARACTERS} characters")
    return normalized


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email_length(cls, value: EmailStr) -> EmailStr:
        normalize_email(value)
        return value

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Full name must not be empty")
        if len(stripped) > MAX_FULL_NAME_CHARACTERS:
            raise ValueError(f"Full name must not exceed {MAX_FULL_NAME_CHARACTERS} characters")
        if any(unicodedata.category(character) == "Cc" for character in stripped):
            raise ValueError("Full name must not contain control characters")
        return stripped

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < MIN_PASSWORD_CODE_POINTS:
            raise ValueError(
                f"Password must contain at least {MIN_PASSWORD_CODE_POINTS} characters"
            )
        if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError(f"Password must not exceed {MAX_PASSWORD_BYTES} UTF-8 bytes")
        return value


class RegisteredUserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    global_role: Literal["STUDENT"]
    status: Literal["ACTIVE"]
    created_at: datetime
