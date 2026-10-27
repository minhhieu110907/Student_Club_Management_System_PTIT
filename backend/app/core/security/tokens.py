"""Opaque refresh-token generation, validation, and one-way persistence digest."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import secrets
from dataclasses import dataclass, field

REFRESH_TOKEN_BYTES = 32
REFRESH_TOKEN_ENCODED_LENGTH = 43
_REDACTED = "<opaque-refresh-token:redacted>"
_BASE64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class RefreshTokenError(ValueError):
    """Raised when an opaque refresh token is malformed."""


@dataclass(frozen=True, slots=True)
class OpaqueRefreshToken:
    _raw: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self._raw, bytes) or len(self._raw) != REFRESH_TOKEN_BYTES:
            raise RefreshTokenError(f"Refresh token must contain {REFRESH_TOKEN_BYTES} bytes")

    def reveal(self) -> str:
        """Reveal only at the HTTP cookie boundary; never pass this value to logs or storage."""
        return base64.urlsafe_b64encode(self._raw).rstrip(b"=").decode("ascii")

    def digest(self) -> bytes:
        """Return the only representation allowed to cross the persistence boundary."""
        return hashlib.sha256(self._raw).digest()

    def __repr__(self) -> str:
        return _REDACTED

    def __str__(self) -> str:
        return _REDACTED


def generate_refresh_token() -> OpaqueRefreshToken:
    return OpaqueRefreshToken(secrets.token_bytes(REFRESH_TOKEN_BYTES))


def parse_refresh_token(encoded: str) -> OpaqueRefreshToken:
    if not isinstance(encoded, str) or len(encoded) != REFRESH_TOKEN_ENCODED_LENGTH:
        raise RefreshTokenError("Refresh token has an invalid encoded length")
    if not _BASE64URL_PATTERN.fullmatch(encoded):
        raise RefreshTokenError("Refresh token must use the unpadded base64url alphabet")
    try:
        raw = base64.b64decode(encoded + "=", altchars=b"-_", validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise RefreshTokenError("Refresh token is not valid base64url") from exc
    canonical = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    if encoded != canonical:
        raise RefreshTokenError("Refresh token is not canonical unpadded base64url")
    return OpaqueRefreshToken(raw)
