"""Shared API dependencies.

A FastAPI *dependency* is a function whose result is passed into a route
handler. Declaring `user: User = Depends(get_current_user)` means the handler
only ever runs for an authenticated request — FastAPI resolves the dependency
first and returns 401 itself if it raises.

That is the mechanism behind the security requirement that users may only
reach their own data: endpoints receive a `User` rather than a user id from
the request, so there is no id for a caller to tamper with.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AuthenticationFailed, InactiveAccount
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import TokenError, decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository

# `auto_error=False` so a missing header reaches our own handler and produces
# the same error shape as every other failure, rather than FastAPI's default.
_bearer_scheme = HTTPBearer(auto_error=False, description="Access token from /auth/login")


def get_settings_from_app(request: Request) -> Settings:
    """The settings the application was created with.

    Read from application state rather than the module-level cache, so tests
    that build an app with their own settings get those settings here too.
    """
    return request.app.state.settings


def get_client_key(request: Request) -> str:
    """Who is making this request, for rate-limiting purposes.

    The client's address, and nothing else. Notably *not* `X-Forwarded-For`:
    that header is set by the caller, so trusting it turns a rate limit into a
    suggestion — anyone refused would simply send a different value. Behind a
    real proxy this would have to read the header *and* trust only the proxy's
    own address, which is a deployment decision this application does not yet
    have to make.

    Falls back to a single shared bucket when there is no address at all, as
    happens with an in-process test transport. Sharing one bucket is the safe
    direction: it throttles more, never less.
    """
    return request.client.host if request.client else "unknown"


def get_login_limiter(request: Request) -> SlidingWindowLimiter:
    return request.app.state.login_limiter


def get_register_limiter(request: Request) -> SlidingWindowLimiter:
    return request.app.state.register_limiter


SettingsDep = Annotated[Settings, Depends(get_settings_from_app)]
SessionDep = Annotated[Session, Depends(get_db)]
CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)]
ClientKey = Annotated[str, Depends(get_client_key)]
LoginLimiter = Annotated[SlidingWindowLimiter, Depends(get_login_limiter)]
RegisterLimiter = Annotated[SlidingWindowLimiter, Depends(get_register_limiter)]


def get_current_user(
    credentials: CredentialsDep,
    session: SessionDep,
    settings: SettingsDep,
) -> User:
    """Resolve the authenticated user, or fail with 401."""
    if credentials is None or not credentials.credentials:
        raise AuthenticationFailed("Not authenticated.")

    try:
        user_id = decode_access_token(credentials.credentials, settings)
    except TokenError as exc:
        # The client is told to sign in again either way; whether the token
        # was expired or forged is a detail for the log, not the response.
        raise AuthenticationFailed(str(exc)) from exc

    user = UserRepository(session).get_by_id(user_id)
    if user is None:
        # A valid signature for a user who no longer exists — a deleted
        # account whose token has not yet expired.
        raise AuthenticationFailed("Account no longer exists.")

    if not user.is_active:
        raise InactiveAccount

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
