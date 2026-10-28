from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.modules.identity.schemas import (
    RegisteredUserResponse,
    RegistrationRequest,
    normalize_email,
)


def test_email_is_validated_and_canonicalized() -> None:
    request = RegistrationRequest(
        email=" Student@Example.COM ", full_name="  Student Name  ", password="abcdefghij"
    )

    assert normalize_email(request.email) == "student@example.com"
    assert request.full_name == "Student Name"
    assert request.password == "abcdefghij"


@pytest.mark.parametrize("email", ["not-an-email", "missing-domain@", "@example.com"])
def test_invalid_email_is_rejected(email: str) -> None:
    with pytest.raises(ValidationError):
        RegistrationRequest(email=email, full_name="Student", password="abcdefghij")


def test_normalized_email_must_fit_database_column() -> None:
    local_part = "a" * 64
    domain = ".".join(["b" * 63, "c" * 63, "d" * 61, "com"])

    with pytest.raises(ValidationError):
        RegistrationRequest(
            email=f"{local_part}@{domain}", full_name="Student", password="abcdefghij"
        )


@pytest.mark.parametrize("full_name", ["", "   ", "Student\x00Name", "a" * 161])
def test_invalid_full_name_is_rejected(full_name: str) -> None:
    with pytest.raises(ValidationError):
        RegistrationRequest(email="student@example.com", full_name=full_name, password="abcdefghij")


def test_password_boundaries_preserve_contents() -> None:
    minimum = " 12345678 "
    maximum = "é" * 512

    assert (
        RegistrationRequest(
            email="student@example.com", full_name="Student", password=minimum
        ).password
        == minimum
    )
    assert (
        RegistrationRequest(
            email="student@example.com", full_name="Student", password=maximum
        ).password
        == maximum
    )

    with pytest.raises(ValidationError):
        RegistrationRequest(email="student@example.com", full_name="Student", password="a" * 9)
    with pytest.raises(ValidationError):
        RegistrationRequest(email="student@example.com", full_name="Student", password="é" * 513)


@pytest.mark.parametrize("field", ["id", "global_role", "status", "password_hash", "created_at"])
def test_internal_fields_are_forbidden(field: str) -> None:
    payload = {
        "email": "student@example.com",
        "full_name": "Student",
        "password": "abcdefghij",
        field: "attacker-controlled",
    }

    with pytest.raises(ValidationError):
        RegistrationRequest.model_validate(payload)


def test_public_response_has_no_secret_fields() -> None:
    response = RegisteredUserResponse(
        id=1,
        email="student@example.com",
        full_name="Student",
        global_role="STUDENT",
        status="ACTIVE",
        created_at=datetime(2026, 10, 28, tzinfo=UTC),
    )

    assert set(response.model_dump()) == {
        "id",
        "email",
        "full_name",
        "global_role",
        "status",
        "created_at",
    }
