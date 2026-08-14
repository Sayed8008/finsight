"""Tests for password hashing and access tokens."""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest

from app.core.config import Settings
from app.core.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        secret_key="unit-test-signing-key-of-sufficient-length", access_token_expire_minutes=60
    )


# ─── Passwords ────────────────────────────────────────────────────────────


def test_hash_does_not_contain_the_password() -> None:
    password = "correct horse battery staple"

    stored = hash_password(password)

    assert password not in stored
    assert stored.startswith("$argon2id$")


def test_correct_password_verifies() -> None:
    stored = hash_password("s3cure-p@ssword")

    assert verify_password("s3cure-p@ssword", stored) is True


def test_wrong_password_is_rejected() -> None:
    stored = hash_password("s3cure-p@ssword")

    assert verify_password("s3cure-p@sswore", stored) is False


def test_same_password_hashes_differently_each_time() -> None:
    """A random salt per hash means identical passwords do not look identical.

    Without it, matching hashes in a stolen database would reveal which
    accounts share a password.
    """
    first = hash_password("same-password")
    second = hash_password("same-password")

    assert first != second
    assert verify_password("same-password", first)
    assert verify_password("same-password", second)


def test_long_password_is_not_truncated() -> None:
    """bcrypt silently ignores everything past 72 bytes; Argon2 does not."""
    base = "x" * 72
    stored = hash_password(base + "AAAA")

    assert verify_password(base + "BBBB", stored) is False


def test_malformed_hash_is_rejected_without_raising() -> None:
    assert verify_password("anything", "not-a-real-hash") is False


# ─── Tokens ───────────────────────────────────────────────────────────────


def test_token_round_trip(settings: Settings) -> None:
    token, expires_in = create_access_token(42, settings)

    assert decode_access_token(token, settings) == 42
    assert expires_in == 3600


def test_expired_token_is_rejected(settings: Settings) -> None:
    token, _ = create_access_token(1, settings, expires_delta=timedelta(seconds=-1))

    with pytest.raises(TokenError, match="expired"):
        decode_access_token(token, settings)


def test_token_signed_with_another_key_is_rejected(settings: Settings) -> None:
    """The whole point of the signature: a token we did not issue is refused."""
    attacker_settings = Settings(secret_key="a-different-key-of-sufficient-length-32")
    token, _ = create_access_token(1, attacker_settings)

    with pytest.raises(TokenError):
        decode_access_token(token, settings)


def test_tampered_payload_is_rejected(settings: Settings) -> None:
    """A JWT is readable by anyone, so the signature must catch edits."""
    token, _ = create_access_token(1, settings)
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    payload["sub"] = "999"
    forged = jwt.encode(
        payload, "wrong-key-but-long-enough-for-hmac-256", algorithm=settings.jwt_algorithm
    )

    with pytest.raises(TokenError):
        decode_access_token(forged, settings)


def test_unsigned_token_is_rejected(settings: Settings) -> None:
    """Guards against the `alg: none` attack."""
    forged = jwt.encode({"sub": "1", "exp": 9999999999}, key="", algorithm="none")

    with pytest.raises(TokenError):
        decode_access_token(forged, settings)


def test_garbage_is_rejected(settings: Settings) -> None:
    with pytest.raises(TokenError):
        decode_access_token("this is not a token", settings)
