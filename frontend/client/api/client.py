"""HTTP client for the FinSight API.

This is the *only* module in the desktop application permitted to perform HTTP
requests. Widgets call methods here; they never touch httpx directly. That
keeps networking, error translation, and authentication in one place instead
of scattered across the interface.

Network errors are translated into `ApiError`, so the interface layer never
has to know which HTTP library is in use or handle its exception types.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx2

from client.api.dto import Token, User
from client.core.config import ClientConfig

logger = logging.getLogger(__name__)

# Path prefix for versioned resources. `/health` sits outside it.
API_V1 = "/api/v1"


class ApiError(Exception):
    """Any failure while talking to the API.

    Carries a message safe to show a user, and optionally the HTTP status.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ApiUnavailableError(ApiError):
    """The backend could not be reached at all (not running, wrong address)."""


class ApiClient:
    """Thin, synchronous wrapper around the FinSight HTTP API.

    Synchronous on purpose for now: calls are to localhost and complete in
    single-digit milliseconds. When a request becomes slow enough to make the
    interface feel unresponsive, it will be moved onto a worker thread rather
    than making this class async.
    """

    def __init__(self, config: ClientConfig | None = None) -> None:
        self._config = config or ClientConfig.from_env()
        self._http = httpx2.Client(
            base_url=self._config.api_base_url,
            timeout=self._config.request_timeout_seconds,
        )
        self._token: str | None = None
        self._v1 = API_V1

    # ─── Authentication state ─────────────────────────────────────────────
    def set_token(self, token: str | None) -> None:
        """Attach (or clear) the access token sent with each request.

        Held in memory only. Writing it to disk would mean protecting it
        there, and re-entering a password on each launch is an acceptable
        trade for a first version. A "stay signed in" option would store a
        refresh token in the OS keyring rather than a plain file.
        """
        self._token = token

    @property
    def is_authenticated(self) -> bool:
        return self._token is not None

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    # ─── Lifecycle ────────────────────────────────────────────────────────
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ─── Requests ─────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {**self._auth_headers(), **kwargs.pop("headers", {})}
        try:
            response = self._http.request(method, path, headers=headers, **kwargs)
        except httpx2.ConnectError as exc:
            logger.warning("Cannot reach API at %s: %s", self._config.api_base_url, exc)
            raise ApiUnavailableError("Cannot reach the FinSight backend. Is it running?") from exc
        except httpx2.TimeoutException as exc:
            logger.warning("API request timed out: %s %s", method, path)
            raise ApiError("The request timed out. Please try again.") from exc

        if response.status_code >= 400:
            raise ApiError(
                self._friendly_error(response),
                status_code=response.status_code,
            )

        if not response.content:
            return None
        return response.json()

    @staticmethod
    def _friendly_error(response: Any) -> str:
        """Turn an error response into a message safe to show a user.

        FastAPI puts a human-readable string in `detail`. Anything else is
        deliberately not surfaced, so internal information cannot leak into
        the interface.
        """
        try:
            detail = response.json().get("detail")
        except Exception:  # noqa: BLE001 - body may not be JSON at all
            detail = None

        if isinstance(detail, str) and detail:
            return detail
        return f"The server returned an error ({response.status_code})."

    # ─── System ───────────────────────────────────────────────────────────
    def health(self) -> dict[str, str]:
        """Check that the backend is running. Raises ApiUnavailableError if not."""
        return self._request("GET", "/health")

    # ─── Authentication ───────────────────────────────────────────────────
    def register(self, email: str, password: str, full_name: str) -> Token:
        """Create an account. The returned token signs the new user in."""
        payload = self._request(
            "POST",
            f"{self._v1}/auth/register",
            json={"email": email, "password": password, "full_name": full_name},
        )
        return Token.from_json(payload)

    def login(self, email: str, password: str) -> Token:
        payload = self._request(
            "POST",
            f"{self._v1}/auth/login",
            json={"email": email, "password": password},
        )
        return Token.from_json(payload)

    def logout(self) -> None:
        self._request("POST", f"{self._v1}/auth/logout")

    def me(self) -> User:
        """The signed-in user. Raises ApiError with status 401 if the token is stale."""
        return User.from_json(self._request("GET", f"{self._v1}/auth/me"))
