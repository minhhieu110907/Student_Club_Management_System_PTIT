import pytest
from pydantic import ValidationError

from app.modules.clubs.schemas import (
    MembershipApplicationCreate,
    MembershipApplicationDecision,
)


def test_membership_application_accepts_trimmed_optional_motivation() -> None:
    assert MembershipApplicationCreate(motivation=None).motivation is None
    assert MembershipApplicationCreate(motivation="  Learn backend  ").motivation == "Learn backend"


@pytest.mark.parametrize("motivation", ["", "   ", "bad\x00text", "x" * 2001])
def test_membership_application_rejects_invalid_motivation(motivation: str) -> None:
    with pytest.raises(ValidationError):
        MembershipApplicationCreate(motivation=motivation)


def test_rejection_reason_is_required_and_bounded() -> None:
    with pytest.raises(ValidationError):
        MembershipApplicationDecision(rejection_reason=" ")
    with pytest.raises(ValidationError):
        MembershipApplicationDecision(rejection_reason="x" * 1001)
    assert (
        MembershipApplicationDecision(rejection_reason="  Not enough detail  ").rejection_reason
        == "Not enough detail"
    )
