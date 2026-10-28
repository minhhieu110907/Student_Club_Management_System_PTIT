from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.identity.exceptions import EmailAlreadyRegisteredError
from app.modules.identity.schemas import RegistrationRequest
from app.modules.identity.service import register_user


def _request() -> RegistrationRequest:
    return RegistrationRequest(
        email="Student@Example.com", full_name="Student", password="abcdefghij"
    )


def _integrity_error(code: int, message: str) -> IntegrityError:
    original = RuntimeError(code, message)
    return IntegrityError("INSERT INTO users", {"password_hash": "secret"}, original)


def test_registration_assigns_student_active_and_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    session.in_transaction.return_value = False
    session.begin.return_value = nullcontext()
    captured = {}

    def fake_add_user(_session, user) -> None:
        captured["user"] = user
        user.id = 17

    monkeypatch.setattr("app.modules.identity.service.hash_password", lambda value: "encoded-hash")
    monkeypatch.setattr("app.modules.identity.service.add_user", fake_add_user)

    response = register_user(_request(), session)

    user = captured["user"]
    assert user.email_normalized == "student@example.com"
    assert user.password_hash == "encoded-hash"
    assert user.global_role == "STUDENT"
    assert user.status == "ACTIVE"
    assert response.id == 17
    assert response.global_role == "STUDENT"
    assert response.status == "ACTIVE"
    assert "password" not in response.model_dump()
    session.begin.assert_called_once_with()


@pytest.mark.parametrize(
    "key_name",
    ["uq_users_email_normalized", "users.uq_users_email_normalized"],
)
def test_exact_email_constraint_maps_to_public_conflict(
    key_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = MagicMock()
    session.in_transaction.return_value = False
    session.begin.return_value = nullcontext()
    monkeypatch.setattr("app.modules.identity.service.hash_password", lambda value: "encoded-hash")
    monkeypatch.setattr(
        "app.modules.identity.service.add_user",
        lambda *_: (_ for _ in ()).throw(
            _integrity_error(1062, f"Duplicate entry for key '{key_name}'")
        ),
    )

    with pytest.raises(EmailAlreadyRegisteredError) as raised:
        register_user(_request(), session)

    assert raised.value.error_code == "EMAIL_ALREADY_REGISTERED"
    session.rollback.assert_called_once_with()


@pytest.mark.parametrize(
    "error",
    [
        _integrity_error(1062, "Duplicate entry for key 'uq_other_constraint'"),
        _integrity_error(1062, "Duplicate entry for key 'uq_users_email_normalized_archive'"),
        _integrity_error(1062, "Duplicate entry for key 'users.prefix_uq_users_email_normalized'"),
        _integrity_error(1452, "Foreign key constraint fails"),
    ],
)
def test_unrelated_integrity_error_propagates(
    error: IntegrityError, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = MagicMock()
    session.in_transaction.return_value = False
    session.begin.return_value = nullcontext()
    monkeypatch.setattr("app.modules.identity.service.hash_password", lambda value: "encoded-hash")
    monkeypatch.setattr(
        "app.modules.identity.service.add_user",
        lambda *_: (_ for _ in ()).throw(error),
    )

    with pytest.raises(IntegrityError) as raised:
        register_user(_request(), session)

    assert raised.value is error
    session.rollback.assert_called_once_with()


def test_active_transaction_is_rejected_before_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    session.in_transaction.return_value = True
    monkeypatch.setattr("app.modules.identity.service.hash_password", lambda value: "encoded-hash")

    with pytest.raises(RuntimeError, match="without an active transaction"):
        register_user(_request(), session)

    session.begin.assert_not_called()
