from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.security.jwt import (
    ACCESS_TOKEN_ALGORITHM,
    ACCESS_TOKEN_TYPE,
    AccessTokenError,
    AccessTokenSettings,
    SecurityConfigurationError,
    create_access_token,
    decode_access_token,
)

NOW = datetime.now(UTC).replace(microsecond=0)
KEY = b"a-cryptographically-random-key-material-for-tests!"
SETTINGS = AccessTokenSettings(signing_key=KEY, issuer="scms-test", audience="scms-api")


def _claims(**overrides: object) -> dict[str, object]:
    claims: dict[str, object] = {
        "sub": "42",
        "iss": SETTINGS.issuer,
        "aud": SETTINGS.audience,
        "iat": int(NOW.timestamp()),
        "nbf": int(NOW.timestamp()),
        "exp": int((NOW + timedelta(minutes=10)).timestamp()),
        "jti": "test-token-id",
        "token_type": ACCESS_TOKEN_TYPE,
    }
    claims.update(overrides)
    return claims


def _encode(claims: dict[str, object], *, key: bytes = KEY, algorithm: str = "HS256") -> str:
    return jwt.encode(claims, key, algorithm=algorithm)


def _encode_without_claim_coercion(claims: dict[str, object]) -> str:
    return jwt.api_jws.encode(json.dumps(claims).encode(), KEY, algorithm="HS256")


def test_valid_access_token_round_trip() -> None:
    token = create_access_token("42", SETTINGS, now=NOW, token_id="fixed-jti")
    decoded = decode_access_token(token, SETTINGS)

    assert decoded.subject == "42"
    assert decoded.token_id == "fixed-jti"
    assert decoded.issued_at == NOW
    assert decoded.expires_at == NOW + timedelta(minutes=10)


def test_exact_600_second_lifetime_is_accepted() -> None:
    issued_at = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=1)
    token = _encode(
        _claims(
            iat=int(issued_at.timestamp()),
            nbf=int(issued_at.timestamp()),
            exp=int((issued_at + timedelta(seconds=600)).timestamp()),
        )
    )

    decoded = decode_access_token(token, SETTINGS)

    assert decoded.expires_at - decoded.issued_at == timedelta(seconds=600)


def test_lifetime_greater_than_600_seconds_is_rejected() -> None:
    issued_at = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=1)
    token = _encode(
        _claims(
            iat=int(issued_at.timestamp()),
            nbf=int(issued_at.timestamp()),
            exp=int((issued_at + timedelta(seconds=601)).timestamp()),
        )
    )

    with pytest.raises(AccessTokenError):
        decode_access_token(token, SETTINGS)


@pytest.mark.parametrize("lifetime", [0, -1])
def test_zero_and_negative_lifetimes_are_rejected(lifetime: int) -> None:
    issued_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
    token = _encode(
        _claims(
            iat=int(issued_at.timestamp()),
            nbf=int(issued_at.timestamp()),
            exp=int((issued_at + timedelta(seconds=lifetime)).timestamp()),
        )
    )

    with pytest.raises(AccessTokenError):
        decode_access_token(token, SETTINGS)


@pytest.mark.parametrize(
    ("iat_offset", "nbf_offset", "exp_offset"),
    [
        (-60, -61, 500),
        (-60, 500, 500),
    ],
)
def test_invalid_iat_nbf_relationships_are_rejected(
    iat_offset: int, nbf_offset: int, exp_offset: int
) -> None:
    current = datetime.now(UTC).replace(microsecond=0)
    token = _encode(
        _claims(
            iat=int((current + timedelta(seconds=iat_offset)).timestamp()),
            nbf=int((current + timedelta(seconds=nbf_offset)).timestamp()),
            exp=int((current + timedelta(seconds=exp_offset)).timestamp()),
        )
    )

    with pytest.raises(AccessTokenError):
        decode_access_token(token, SETTINGS)


def test_future_iat_and_future_nbf_are_rejected() -> None:
    current = datetime.now(UTC).replace(microsecond=0)
    future_iat = _encode(
        _claims(
            iat=int((current + timedelta(minutes=1)).timestamp()),
            nbf=int((current + timedelta(minutes=1)).timestamp()),
            exp=int((current + timedelta(minutes=10)).timestamp()),
        )
    )
    future_nbf = _encode(
        _claims(
            iat=int(current.timestamp()),
            nbf=int((current + timedelta(minutes=1)).timestamp()),
            exp=int((current + timedelta(minutes=10)).timestamp()),
        )
    )

    with pytest.raises(AccessTokenError):
        decode_access_token(future_iat, SETTINGS)
    with pytest.raises(AccessTokenError):
        decode_access_token(future_nbf, SETTINGS)


@pytest.mark.parametrize(
    ("claims", "settings"),
    [
        (_claims(exp=int((NOW - timedelta(seconds=1)).timestamp())), SETTINGS),
        (_claims(iss="other"), SETTINGS),
        (_claims(aud="other"), SETTINGS),
    ],
)
def test_expired_wrong_issuer_and_wrong_audience_are_rejected(
    claims: dict[str, object], settings: AccessTokenSettings
) -> None:
    with pytest.raises(AccessTokenError):
        decode_access_token(_encode(claims), settings)


def test_wrong_algorithm_and_invalid_signature_are_rejected() -> None:
    with pytest.raises(AccessTokenError):
        decode_access_token(_encode(_claims(), algorithm="HS384"), SETTINGS)
    with pytest.raises(AccessTokenError):
        decode_access_token(_encode(_claims(), key=b"different-signing-key-material!!"), SETTINGS)


@pytest.mark.parametrize("missing", ["sub", "iss", "aud", "iat", "nbf", "exp", "jti", "token_type"])
def test_every_required_claim_is_enforced(missing: str) -> None:
    claims = _claims()
    claims.pop(missing)
    with pytest.raises(AccessTokenError):
        decode_access_token(_encode(claims), SETTINGS)


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("sub", 42),
        ("iss", 42),
        ("aud", ["scms-api"]),
        ("iat", "now"),
        ("nbf", True),
        ("exp", 1.5),
        ("jti", 42),
        ("token_type", 42),
    ],
)
def test_invalid_claim_types_are_rejected(claim: str, value: object) -> None:
    with pytest.raises(AccessTokenError):
        decode_access_token(_encode_without_claim_coercion(_claims(**{claim: value})), SETTINGS)


def test_invalid_token_type_and_malformed_token_are_rejected() -> None:
    with pytest.raises(AccessTokenError):
        decode_access_token(_encode(_claims(token_type="refresh")), SETTINGS)
    with pytest.raises(AccessTokenError):
        decode_access_token("not.a.jwt", SETTINGS)


def test_configuration_requires_unpadded_base64url_secret_and_identity() -> None:
    encoded = base64.urlsafe_b64encode(KEY).rstrip(b"=").decode("ascii")
    settings = AccessTokenSettings.from_environment(
        {
            "SCMS_JWT_SECRET": encoded,
            "SCMS_JWT_ISSUER": "scms-test",
            "SCMS_JWT_AUDIENCE": "scms-api",
        }
    )
    assert settings.signing_key == KEY
    assert "cryptographically-random" not in repr(settings)

    canonical_32_byte_secret = base64.urlsafe_b64encode(bytes(32)).rstrip(b"=").decode("ascii")
    noncanonical_secret = canonical_32_byte_secret[:-1] + "B"

    invalid_environments = [
        {},
        {"SCMS_JWT_SECRET": "short", "SCMS_JWT_ISSUER": "i", "SCMS_JWT_AUDIENCE": "a"},
        {
            "SCMS_JWT_SECRET": encoded + "=",
            "SCMS_JWT_ISSUER": "i",
            "SCMS_JWT_AUDIENCE": "a",
        },
        {"SCMS_JWT_SECRET": encoded, "SCMS_JWT_ISSUER": "", "SCMS_JWT_AUDIENCE": "a"},
        {"SCMS_JWT_SECRET": encoded, "SCMS_JWT_ISSUER": "i", "SCMS_JWT_AUDIENCE": ""},
        {
            "SCMS_JWT_SECRET": "A" * 42 + "+",
            "SCMS_JWT_ISSUER": "i",
            "SCMS_JWT_AUDIENCE": "a",
        },
        {
            "SCMS_JWT_SECRET": noncanonical_secret,
            "SCMS_JWT_ISSUER": "i",
            "SCMS_JWT_AUDIENCE": "a",
        },
    ]
    for environment in invalid_environments:
        with pytest.raises(SecurityConfigurationError):
            AccessTokenSettings.from_environment(environment)


@pytest.mark.parametrize(
    "overrides",
    [
        {"signing_key": "not-bytes"},
        {"issuer": 42},
        {"audience": 42},
        {"ttl": timedelta(minutes=11)},
    ],
)
def test_runtime_settings_reject_invalid_types_and_ttl(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "signing_key": KEY,
        "issuer": "scms-test",
        "audience": "scms-api",
        "ttl": timedelta(minutes=10),
    }
    values.update(overrides)

    with pytest.raises(SecurityConfigurationError):
        AccessTokenSettings(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("extreme", [10**100, -(10**100)])
def test_extreme_signed_numeric_dates_stay_inside_error_boundary(extreme: int) -> None:
    token = _encode_without_claim_coercion(_claims(iat=extreme, nbf=extreme, exp=extreme + 600))

    with pytest.raises(AccessTokenError):
        decode_access_token(token, SETTINGS)


def test_unrepresentable_timestamps_from_decoder_are_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extreme = 10**100
    monkeypatch.setattr(
        jwt,
        "decode",
        lambda *args, **kwargs: _claims(iat=extreme, nbf=extreme, exp=extreme + 600),
    )

    with pytest.raises(AccessTokenError):
        decode_access_token("syntactically-irrelevant-in-this-unit-test", SETTINGS)


def test_create_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        create_access_token("42", SETTINGS, now=datetime(2026, 1, 1))


def test_algorithm_constant_is_explicit() -> None:
    assert ACCESS_TOKEN_ALGORITHM == "HS256"
