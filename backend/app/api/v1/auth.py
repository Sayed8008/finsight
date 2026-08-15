"""Authentication endpoints.

Route handlers stay thin: validate input (Pydantic does this), call a service,
shape the response. No business rules and no queries appear here.

The one thing that does live here is throttling, and it belongs here rather
than in `AuthService` for a specific reason: it is a property of *the caller*,
not of the credentials. The service answers "are these the right details for
this account"; how often somebody may ask that question is a question about the
HTTP client asking it, and the service has no idea one exists. Keeping it at
this layer also means the service stays testable without inventing a request.

The counting rule is that only failures count, and a success clears the record.
Somebody who mistypes their password twice and then gets it right is not one
attempt from being locked out — the thing worth limiting is guessing, and a
correct password is not a guess.
"""

from __future__ import annotations

from time import monotonic

from fastapi import APIRouter, status

from app.api.v1.deps import (
    ClientKey,
    CurrentUser,
    LoginLimiter,
    RegisterLimiter,
    SessionDep,
    SettingsDep,
)
from app.core.exceptions import AuthenticationFailed, TooManyAttempts
from app.core.rate_limit import SlidingWindowLimiter
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["authentication"])


def _refuse_if_throttled(limiter: SlidingWindowLimiter, key: str) -> None:
    """Stop before the password is checked, not after.

    Checked first so that a refused request costs an Argon2 verification less.
    That is not only about server load: verification takes long enough to be
    measurable, so a throttle applied afterwards would still let an attacker
    time the response.

    `monotonic` rather than wall-clock time. A clock adjustment — an NTP step,
    daylight saving — must not hand out a fresh allowance or lock somebody out
    for an hour, and monotonic time cannot go backwards.
    """
    decision = limiter.check(key, monotonic())
    if not decision.allowed:
        raise TooManyAttempts(decision.retry_after_seconds)


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    responses={
        409: {"description": "Email already registered"},
        429: {"description": "Too many accounts created from this address"},
    },
)
def register(
    payload: RegisterRequest,
    session: SessionDep,
    settings: SettingsDep,
    client: ClientKey,
    limiter: RegisterLimiter,
) -> TokenResponse:
    """Register a new user and sign them in.

    A default set of categories is created with the account, so the user can
    record a transaction immediately rather than having to set up categories
    first.

    A token is returned directly, since making someone log in immediately
    after registering serves no purpose.

    Throttled more tightly than signing in, and counting *successes* rather
    than failures: what is worth limiting here is accounts being created, and
    each one costs a row in every table plus fifteen seeded categories.
    """
    _refuse_if_throttled(limiter, client)

    service = AuthService(session, settings)
    user = service.register(payload.email, payload.password, payload.full_name)
    limiter.record(client, monotonic())
    token, expires_in = service.issue_token(user)

    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Sign in",
    responses={
        401: {"description": "Incorrect email or password"},
        429: {"description": "Too many failed attempts from this address"},
    },
)
def login(
    payload: LoginRequest,
    session: SessionDep,
    settings: SettingsDep,
    client: ClientKey,
    limiter: LoginLimiter,
) -> TokenResponse:
    """Exchange email and password for an access token.

    Without a limit here, this form is an offline password guesser with a
    network in front of it. Argon2 makes each guess expensive, which narrows
    the gap; it does not close it.

    Attempts are counted per client address rather than per email, which is the
    less obvious choice and the right one. Counting per email would let anybody
    who knows an address lock its owner out by failing ten logins on their
    behalf — the protection would become the attack.
    """
    _refuse_if_throttled(limiter, client)

    service = AuthService(session, settings)
    try:
        user = service.authenticate(payload.email, payload.password)
    except AuthenticationFailed:
        limiter.record(client, monotonic())
        # Re-raised unchanged. A message that revealed how many attempts were
        # left would hand an attacker a progress bar, and one that appeared
        # only for real accounts would answer "does this email exist?"
        # (ADR-018).
        raise

    # A correct password is not a guess, so the record goes rather than being
    # left to expire — otherwise two typos this morning would still count
    # against somebody this afternoon.
    limiter.clear(client)
    token, expires_in = service.issue_token(user)

    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out",
)
def logout(current_user: CurrentUser) -> None:
    """Sign out.

    Access tokens are stateless: the server holds no session to end, so this
    endpoint cannot make an already-issued token stop working. Logging out is
    the client discarding its token, which the desktop application does.

    The endpoint exists so that the client has one place to call, and so the
    event can be logged. Genuinely revoking a token before it expires would
    require storing issued tokens and checking a denylist on every request —
    real work, deferred until there is a reason for it. Token lifetime is
    kept short instead.
    """
    return None


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Current user",
    responses={401: {"description": "Not authenticated"}},
)
def read_current_user(current_user: CurrentUser) -> UserResponse:
    """Return the signed-in user.

    Used by the desktop client at startup to check whether a stored token is
    still valid before showing the main window.
    """
    return UserResponse.model_validate(current_user)
