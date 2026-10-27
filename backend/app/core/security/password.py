"""Argon2id password hashing with bounded caller-controlled input."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MAX_PASSWORD_BYTES = 1024

_PASSWORD_HASHER = PasswordHasher()


class PasswordValidationError(ValueError):
    """Raised when a plaintext password violates a primitive-level bound."""


def _validated_password(password: str) -> str:
    if not isinstance(password, str):
        raise PasswordValidationError("Password must be a string")
    if not password:
        raise PasswordValidationError("Password must not be empty")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise PasswordValidationError(f"Password must not exceed {MAX_PASSWORD_BYTES} UTF-8 bytes")
    return password


def hash_password(password: str) -> str:
    """Return a self-describing Argon2id hash for a validated password."""
    return _PASSWORD_HASHER.hash(_validated_password(password))


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a password without propagating attacker-controlled hash parse errors."""
    password = _validated_password(password)
    try:
        return _PASSWORD_HASHER.verify(encoded_hash, password)
    except (InvalidHashError, VerificationError, TypeError):
        return False


def password_needs_rehash(encoded_hash: str) -> bool:
    """Report whether a valid hash uses parameters older than the current policy."""
    try:
        return _PASSWORD_HASHER.check_needs_rehash(encoded_hash)
    except (InvalidHashError, TypeError):
        return False
