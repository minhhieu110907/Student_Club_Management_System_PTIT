import pytest
from argon2 import PasswordHasher, Type

from app.core.security.password import (
    MAX_PASSWORD_BYTES,
    PasswordValidationError,
    hash_password,
    password_needs_rehash,
    verify_password,
)


def test_hash_and_verify_password_with_independent_salts() -> None:
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")

    assert first.startswith("$argon2id$")
    assert second.startswith("$argon2id$")
    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert not verify_password("incorrect", first)


def test_needs_rehash_detects_older_parameters() -> None:
    legacy = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1, type=Type.ID)
    encoded = legacy.hash("upgrade me")

    assert password_needs_rehash(encoded)
    assert not password_needs_rehash(hash_password("current"))


def test_unicode_and_utf8_byte_boundaries() -> None:
    boundary = "é" * (MAX_PASSWORD_BYTES // 2)
    encoded = hash_password(boundary)

    assert verify_password(boundary, encoded)
    with pytest.raises(PasswordValidationError, match="UTF-8 bytes"):
        hash_password(boundary + "é")


@pytest.mark.parametrize("malformed", ["", "not-a-hash", "$argon2id$broken"])
def test_malformed_hash_is_rejected_without_propagating_parser_errors(malformed: str) -> None:
    assert not verify_password("password", malformed)
    assert not password_needs_rehash(malformed)


def test_empty_password_is_rejected() -> None:
    with pytest.raises(PasswordValidationError, match="must not be empty"):
        hash_password("")
