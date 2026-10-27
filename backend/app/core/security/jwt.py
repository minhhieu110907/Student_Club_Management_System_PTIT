"""HTTP-independent creation and validation of short-lived access JWTs."""

from __future__ import annotations

import base64
import binascii
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt

ACCESS_TOKEN_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(minutes=10)
ACCESS_TOKEN_TYPE = "access"
MINIMUM_SIGNING_KEY_BYTES = 32
_BASE64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class SecurityConfigurationError(ValueError):
    """Raised when required security configuration is absent or unsafe."""


class AccessTokenError(ValueError):
    """Raised when an access token fails cryptographic or claim validation."""


@dataclass(frozen=True, slots=True)
class AccessTokenSettings:
    signing_key: bytes = field(repr=False)
    issuer: str
    audience: str
    ttl: timedelta = ACCESS_TOKEN_TTL

    def __post_init__(self) -> None:
        if not isinstance(self.signing_key, bytes):
            raise SecurityConfigurationError("JWT signing key must be bytes")
        if len(self.signing_key) < MINIMUM_SIGNING_KEY_BYTES:
            raise SecurityConfigurationError(
                f"JWT signing key must contain at least {MINIMUM_SIGNING_KEY_BYTES} bytes"
            )
        if not isinstance(self.issuer, str) or not self.issuer.strip():
            raise SecurityConfigurationError("JWT issuer must not be empty")
        if not isinstance(self.audience, str) or not self.audience.strip():
            raise SecurityConfigurationError("JWT audience must not be empty")
        if self.ttl != ACCESS_TOKEN_TTL:
            raise SecurityConfigurationError("V1 access-token TTL must be exactly 10 minutes")

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> AccessTokenSettings:
        values = os.environ if environment is None else environment
        encoded_secret = values.get("SCMS_JWT_SECRET", "")
        try:
            signing_key = _decode_base64url_secret(encoded_secret)
        except ValueError as exc:
            raise SecurityConfigurationError(str(exc)) from exc
        return cls(
            signing_key=signing_key,
            issuer=values.get("SCMS_JWT_ISSUER", "").strip(),
            audience=values.get("SCMS_JWT_AUDIENCE", "").strip(),
        )


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    subject: str
    token_id: str
    issued_at: datetime
    not_before: datetime
    expires_at: datetime


def create_access_token(
    subject: str,
    settings: AccessTokenSettings,
    *,
    now: datetime | None = None,
    token_id: str | None = None,
) -> str:
    issued_at = _aware_utc(now or datetime.now(UTC))
    if not isinstance(subject, str) or not subject:
        raise ValueError("Access-token subject must be a non-empty string")
    jti = token_id or str(uuid4())
    if not isinstance(jti, str) or not jti:
        raise ValueError("Access-token ID must be a non-empty string")

    payload = {
        "sub": subject,
        "iss": settings.issuer,
        "aud": settings.audience,
        "iat": issued_at,
        "nbf": issued_at,
        "exp": issued_at + settings.ttl,
        "jti": jti,
        "token_type": ACCESS_TOKEN_TYPE,
    }
    return jwt.encode(payload, settings.signing_key, algorithm=ACCESS_TOKEN_ALGORITHM)


def decode_access_token(
    token: str,
    settings: AccessTokenSettings,
) -> AccessTokenClaims:
    if not isinstance(token, str) or not token:
        raise AccessTokenError("Malformed access token")

    options: dict[str, Any] = {
        "require": ["sub", "iss", "aud", "iat", "nbf", "exp", "jti", "token_type"],
        "verify_signature": True,
        "verify_exp": True,
        "verify_nbf": True,
        "verify_iat": True,
        "verify_iss": True,
        "verify_aud": True,
    }
    try:
        payload = jwt.decode(
            token,
            settings.signing_key,
            algorithms=[ACCESS_TOKEN_ALGORITHM],
            audience=settings.audience,
            issuer=settings.issuer,
            options=options,
        )
        _validate_claim_types(payload)
        _validate_temporal_contract(payload, settings.ttl)
        issued_at = datetime.fromtimestamp(payload["iat"], UTC)
        not_before = datetime.fromtimestamp(payload["nbf"], UTC)
        expires_at = datetime.fromtimestamp(payload["exp"], UTC)
    except (jwt.PyJWTError, TypeError, ValueError, OverflowError, OSError) as exc:
        raise AccessTokenError("Invalid access token") from exc

    return AccessTokenClaims(
        subject=payload["sub"],
        token_id=payload["jti"],
        issued_at=issued_at,
        not_before=not_before,
        expires_at=expires_at,
    )


def _validate_claim_types(payload: Mapping[str, Any]) -> None:
    for claim in ("sub", "iss", "aud", "jti", "token_type"):
        if not isinstance(payload.get(claim), str) or not payload[claim]:
            raise AccessTokenError(f"Invalid {claim} claim")
    for claim in ("iat", "nbf", "exp"):
        value = payload.get(claim)
        if isinstance(value, bool) or not isinstance(value, int):
            raise AccessTokenError(f"Invalid {claim} claim")
    if payload["token_type"] != ACCESS_TOKEN_TYPE:
        raise AccessTokenError("Invalid access-token type")


def _validate_temporal_contract(payload: Mapping[str, Any], ttl: timedelta) -> None:
    issued_at = payload["iat"]
    not_before = payload["nbf"]
    expires_at = payload["exp"]
    if not issued_at <= not_before < expires_at:
        raise AccessTokenError("Invalid access-token timestamp order")
    if expires_at - issued_at > int(ttl.total_seconds()):
        raise AccessTokenError("Access-token lifetime exceeds the configured maximum")


def _decode_base64url_secret(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("SCMS_JWT_SECRET is required")
    if not _BASE64URL_PATTERN.fullmatch(value):
        raise ValueError("SCMS_JWT_SECRET must use the unpadded base64url alphabet")
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("SCMS_JWT_SECRET must be valid unpadded base64url") from exc
    if len(decoded) < MINIMUM_SIGNING_KEY_BYTES:
        raise ValueError(
            f"SCMS_JWT_SECRET must decode to at least {MINIMUM_SIGNING_KEY_BYTES} bytes"
        )
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if value != canonical:
        raise ValueError("SCMS_JWT_SECRET must use canonical unpadded base64url encoding")
    return decoded


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware")
    return value.astimezone(UTC)
