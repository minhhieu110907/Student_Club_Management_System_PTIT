import hashlib
import io
import logging
import secrets

import pytest

from app.core.security.tokens import (
    REFRESH_TOKEN_BYTES,
    OpaqueRefreshToken,
    RefreshTokenError,
    generate_refresh_token,
    parse_refresh_token,
)


def test_generation_uses_exact_entropy_length_and_tokens_are_distinct() -> None:
    tokens = [generate_refresh_token() for _ in range(16)]

    assert all(len(token.reveal()) == 43 for token in tokens)
    assert len({token.reveal() for token in tokens}) == len(tokens)


def test_generation_requests_32_bytes_from_system_csprng(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_lengths: list[int] = []

    def deterministic_token_bytes(length: int) -> bytes:
        requested_lengths.append(length)
        return bytes(range(length))

    monkeypatch.setattr(secrets, "token_bytes", deterministic_token_bytes)

    token = generate_refresh_token()

    assert requested_lengths == [REFRESH_TOKEN_BYTES]
    assert token.digest() == hashlib.sha256(bytes(range(REFRESH_TOKEN_BYTES))).digest()


def test_round_trip_and_digest_are_deterministic() -> None:
    raw = bytes(range(REFRESH_TOKEN_BYTES))
    token = OpaqueRefreshToken(raw)
    parsed = parse_refresh_token(token.reveal())

    assert parsed.digest() == hashlib.sha256(raw).digest()
    assert parsed.digest() == token.digest()


def test_noncanonical_base64url_is_rejected() -> None:
    canonical = OpaqueRefreshToken(bytes(REFRESH_TOKEN_BYTES)).reveal()
    noncanonical = canonical[:-1] + "B"

    with pytest.raises(RefreshTokenError, match="canonical"):
        parse_refresh_token(noncanonical)


@pytest.mark.parametrize(
    "encoded",
    [
        "",
        "short",
        "a" * 42,
        "a" * 44,
        "=" * 43,
        "!" * 43,
        "a" * 42 + "+",
        "a" * 42 + "/",
        "é" * 43,
    ],
)
def test_invalid_encoding_or_length_is_rejected(encoded: str) -> None:
    with pytest.raises(RefreshTokenError):
        parse_refresh_token(encoded)


@pytest.mark.parametrize("length", [REFRESH_TOKEN_BYTES - 1, REFRESH_TOKEN_BYTES + 1])
def test_decoded_length_violations_are_rejected(length: int) -> None:
    with pytest.raises(RefreshTokenError, match="32 bytes"):
        OpaqueRefreshToken(bytes(length))


def test_repr_str_and_logging_do_not_expose_plaintext() -> None:
    token = generate_refresh_token()
    plaintext = token.reveal()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("scms.security-test")
    logger.addHandler(handler)
    logger.propagate = False
    logger.setLevel(logging.INFO)

    try:
        logger.info("token=%s repr=%r", token, token)
    finally:
        logger.removeHandler(handler)

    assert plaintext not in repr(token)
    assert plaintext not in str(token)
    assert plaintext not in stream.getvalue()
    assert "redacted" in stream.getvalue()
