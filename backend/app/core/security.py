"""Password hashing and access tokens.

Two separate concerns live here, both security-critical and both small enough
that keeping them in one place makes them easy to review.

**Password hashing** uses Argon2id (ADR-004). A hash is deliberately slow to
compute, so that someone who steals the database cannot test billions of
candidate passwords per second. The stored value contains the algorithm, its
parameters and a random salt, so no separate salt column is needed.

**Access tokens** are JSON Web Tokens: a small signed JSON payload the client
sends back with each request. The signature proves the server issued it, so
the server can trust the user id inside without a database lookup on every
request. A JWT is *signed, not encrypted* — anyone holding one can read its
contents, so it must never carry anything secret.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings

logger = logging.getLogger(__name__)

# Default parameters follow argon2-cffi's current recommendations. They are
# defined once here so that raising the cost later is a one-line change.
_password_hasher = PasswordHasher()

# Hashing this on a failed login makes a missing account take about as long as
# a wrong password, so response time does not reveal which emails are
# registered.
_DUMMY_HASH = _password_hasher.hash("timing-attack-mitigation-placeholder")

TOKEN_TYPE = "access"


# ─── Passwords ────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Return an Argon2id hash of `password`, salt included."""
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a password against a stored hash.

    Returns False rather than raising, because from the caller's point of view
    every failure mode — wrong password, corrupt hash — means the same thing:
    do not log this person in.
    """
    try:
        return _password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except (VerificationError, InvalidHashError):
        logger.warning("Password verification failed against a malformed hash")
        return False


def waste_time_like_a_failed_verification() -> None:
    """Spend roughly the time a real verification would take.

    Called when no account exists for the submitted email. Without it, a
    missing account returns noticeably faster than a wrong password, which
    lets an attacker discover which email addresses are registered.
    """
    try:
        _password_hasher.verify(_DUMMY_HASH, "not-the-password")
    except VerifyMismatchError:
        pass


def password_needs_rehash(password_hash: str) -> bool:
    """True if the hash uses older parameters than the current settings.

    Lets cost parameters be raised over time: on a successful login with an
    outdated hash, the password can be re-hashed and stored.
    """
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# ─── Access tokens ────────────────────────────────────────────────────────


def create_access_token(
    user_id: int,
    settings: Settings,
    *,
    expires_delta: timedelta | None = None,
) -> tuple[str, int]:
    """Create a signed access token for a user.

    Returns the token and its lifetime in seconds, so the client can decide
    when to ask for a new one rather than waiting to be rejected.
    """
    lifetime = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    issued_at = datetime.now(UTC)

    payload: dict[str, Any] = {
        # `sub` is the standard claim for "who this token is about". It must
        # be a string; some JWT libraries reject a numeric value.
        "sub": str(user_id),
        "iat": issued_at,
        "exp": issued_at + lifetime,
        "type": TOKEN_TYPE,
    }

    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, int(lifetime.total_seconds())


class TokenError(Exception):
    """A token was missing, malformed, expired, or not signed by us."""


def decode_access_token(token: str, settings: Settings) -> int:
    """Verify a token and return the user id it identifies.

    Raises `TokenError` for every failure. The caller should not distinguish
    between "expired" and "forged" when responding to the client — both mean
    "authenticate again" — though they are logged differently here.
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        # Covers a bad signature, malformed structure and unsupported
        # algorithms. Logged at warning level because a forged token is worth
        # noticing; an expired one is routine.
        logger.warning("Rejected an invalid access token: %s", exc)
        raise TokenError("Token is invalid") from exc

    if payload.get("type") != TOKEN_TYPE:
        raise TokenError("Token is not an access token")

    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenError("Token subject is not a valid user id") from exc
