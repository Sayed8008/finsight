"""Authentication endpoints.

Route handlers stay thin: validate input (Pydantic does this), call a service,
shape the response. No business rules and no queries appear here.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.v1.deps import CurrentUser, SessionDep, SettingsDep
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    responses={409: {"description": "Email already registered"}},
)
def register(
    payload: RegisterRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    """Register a new user and sign them in.

    A default set of categories is created with the account, so the user can
    record a transaction immediately rather than having to set up categories
    first.

    A token is returned directly, since making someone log in immediately
    after registering serves no purpose.
    """
    service = AuthService(session, settings)
    user = service.register(payload.email, payload.password, payload.full_name)
    token, expires_in = service.issue_token(user)

    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Sign in",
    responses={401: {"description": "Incorrect email or password"}},
)
def login(
    payload: LoginRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    """Exchange email and password for an access token."""
    service = AuthService(session, settings)
    user = service.authenticate(payload.email, payload.password)
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
