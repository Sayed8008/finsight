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

from client.core.config import ClientConfig

logger = logging.getLogger(__name__)


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

    # ─── Lifecycle ────────────────────────────────────────────────────────
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ─── Requests ─────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._http.request(method, path, **kwargs)
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

    # ─── Endpoints ────────────────────────────────────────────────────────
    def health(self) -> dict[str, str]:
        """Check that the backend is running. Raises ApiUnavailableError if not."""
        return self._request("GET", "/health")
