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

from client.api.dto import (
    Budget,
    Category,
    Comparison,
    Dashboard,
    Detection,
    Insights,
    Subscription,
    SubscriptionSummary,
    Token,
    Transaction,
    TransactionPage,
    Trend,
    User,
)
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

    # ─── Categories ───────────────────────────────────────────────────────
    def categories(self, *, include_inactive: bool = False) -> list[Category]:
        """Every category belonging to the signed-in user.

        Fetched once per view and kept, rather than per table row — the same
        fifteen names would otherwise be requested once for each transaction on
        screen.
        """
        payload = self._request(
            "GET",
            f"{self._v1}/categories",
            params=_without_none({"include_inactive": include_inactive or None}),
        )
        return [Category.from_json(item) for item in payload]

    def create_category(
        self, name: str, category_type: str, *, color: str | None = None
    ) -> Category:
        payload = self._request(
            "POST",
            f"{self._v1}/categories",
            json=_without_none({"name": name, "category_type": category_type, "color": color}),
        )
        return Category.from_json(payload)

    def update_category(self, category_id: int, **changes: Any) -> Category:
        """Rename, recolour, deactivate or restore a category.

        Only the keys passed are sent, so this is a genuine PATCH: omitting
        `color` leaves the colour alone rather than clearing it. There is no
        delete — a category is retired by `is_active=False`.
        """
        payload = self._request("PATCH", f"{self._v1}/categories/{category_id}", json=changes)
        return Category.from_json(payload)

    # ─── Transactions ─────────────────────────────────────────────────────
    def transactions(
        self,
        *,
        page: int = 1,
        page_size: int = 25,
        sort_by: str = "date",
        order: str = "desc",
        date_from: str | None = None,
        date_to: str | None = None,
        transaction_type: str | None = None,
        category_id: int | None = None,
        payment_method: str | None = None,
        amount_min: str | None = None,
        amount_max: str | None = None,
        search: str | None = None,
    ) -> TransactionPage:
        """One page of transactions.

        Every filter is passed to the server, which does the filtering, sorting
        and paging in SQL. Doing any of it here would only ever narrow the page
        already received — 25 rows out of however many there are.

        Amount bounds are passed as strings for the same reason they arrive as
        strings: a float in a query parameter is a float.
        """
        params = _without_none(
            {
                "page": page,
                "page_size": page_size,
                "sort_by": sort_by,
                "order": order,
                "date_from": date_from,
                "date_to": date_to,
                "transaction_type": transaction_type,
                "category_id": category_id,
                "payment_method": payment_method,
                "amount_min": amount_min,
                "amount_max": amount_max,
                "search": search,
            }
        )
        return TransactionPage.from_json(
            self._request("GET", f"{self._v1}/transactions", params=params)
        )

    def create_transaction(self, **fields: Any) -> Transaction:
        payload = self._request("POST", f"{self._v1}/transactions", json=fields)
        return Transaction.from_json(payload)

    def update_transaction(self, transaction_id: int, **changes: Any) -> Transaction:
        payload = self._request("PATCH", f"{self._v1}/transactions/{transaction_id}", json=changes)
        return Transaction.from_json(payload)

    def delete_transaction(self, transaction_id: int) -> None:
        self._request("DELETE", f"{self._v1}/transactions/{transaction_id}")

    def payment_methods(self) -> list[str]:
        """The payment methods this user has actually recorded.

        Used to fill the filter list with real values, rather than asking the
        user to remember how they spelled "bKash" last time.
        """
        return list(self._request("GET", f"{self._v1}/transactions/payment-methods"))

    # ─── Budgets ──────────────────────────────────────────────────────────
    def budgets(
        self, *, category_id: int | None = None, current_only: bool = False
    ) -> list[Budget]:
        """Budgets with their utilisation already worked out.

        Spent, remaining, percentage and status arrive computed. The client
        never recalculates them: a second implementation of the thresholds is a
        second thing to keep in step, and the two would eventually disagree.
        """
        payload = self._request(
            "GET",
            f"{self._v1}/budgets",
            params=_without_none(
                {"category_id": category_id, "current_only": current_only or None}
            ),
        )
        return [Budget.from_json(item) for item in payload]

    def create_budget(self, **fields: Any) -> Budget:
        return Budget.from_json(self._request("POST", f"{self._v1}/budgets", json=fields))

    def update_budget(self, budget_id: int, **changes: Any) -> Budget:
        payload = self._request("PATCH", f"{self._v1}/budgets/{budget_id}", json=changes)
        return Budget.from_json(payload)

    def delete_budget(self, budget_id: int) -> None:
        self._request("DELETE", f"{self._v1}/budgets/{budget_id}")

    # ─── Subscriptions ────────────────────────────────────────────────────
    def subscriptions(
        self,
        *,
        status: str | None = None,
        category_id: int | None = None,
        due_within_days: int | None = None,
    ) -> list[Subscription]:
        """Subscriptions with their costs and renewal timing already worked out."""
        payload = self._request(
            "GET",
            f"{self._v1}/subscriptions",
            params=_without_none(
                {
                    "subscription_status": status,
                    "category_id": category_id,
                    "due_within_days": due_within_days,
                }
            ),
        )
        return [Subscription.from_json(item) for item in payload]

    def subscription_summary(self) -> SubscriptionSummary:
        """Monthly and yearly commitment, and what renews next."""
        return SubscriptionSummary.from_json(
            self._request("GET", f"{self._v1}/subscriptions/summary")
        )

    def create_subscription(self, **fields: Any) -> Subscription:
        payload = self._request("POST", f"{self._v1}/subscriptions", json=fields)
        return Subscription.from_json(payload)

    def update_subscription(self, subscription_id: int, **changes: Any) -> Subscription:
        payload = self._request(
            "PATCH", f"{self._v1}/subscriptions/{subscription_id}", json=changes
        )
        return Subscription.from_json(payload)

    def renew_subscription(self, subscription_id: int) -> Subscription:
        """Record that the charge was taken and move to the next billing date."""
        payload = self._request("POST", f"{self._v1}/subscriptions/{subscription_id}/renew")
        return Subscription.from_json(payload)

    def delete_subscription(self, subscription_id: int) -> None:
        self._request("DELETE", f"{self._v1}/subscriptions/{subscription_id}")

    def detect_subscriptions(
        self, *, lookback_days: int = 365, include_tracked: bool = False
    ) -> Detection:
        """Ask the server to look for subscriptions in transaction history.

        Returns proposals only. Nothing is created until the user confirms one
        (ADR-007), which is why every candidate arrives with its evidence.
        """
        payload = self._request(
            "POST",
            f"{self._v1}/subscriptions/detect",
            params=_without_none(
                {"lookback_days": lookback_days, "include_tracked": include_tracked or None}
            ),
        )
        return Detection.from_json(payload)

    # ─── Dashboard ────────────────────────────────────────────────────────
    def dashboard(
        self, *, period_start: str | None = None, period_end: str | None = None
    ) -> Dashboard:
        """Everything the first screen needs, in one request.

        Deliberately one call rather than five. Five would mean five loading
        states and five chances to show figures taken at different moments.
        """
        payload = self._request(
            "GET",
            f"{self._v1}/dashboard",
            params=_without_none({"period_start": period_start, "period_end": period_end}),
        )
        return Dashboard.from_json(payload)

    # ─── Analytics ────────────────────────────────────────────────────────
    def trend(self, *, months: int = 6) -> Trend:
        """Income and expense per month, with empty months filled in."""
        payload = self._request("GET", f"{self._v1}/analytics/trend", params={"months": months})
        return Trend.from_json(payload)

    def comparison(
        self, *, period_start: str | None = None, period_end: str | None = None
    ) -> Comparison:
        """A period against the one before it. The window is derived server-side."""
        payload = self._request(
            "GET",
            f"{self._v1}/analytics/comparison",
            params=_without_none({"period_start": period_start, "period_end": period_end}),
        )
        return Comparison.from_json(payload)

    # ─── Insights ─────────────────────────────────────────────────────────
    def insights(
        self, *, period_start: str | None = None, period_end: str | None = None
    ) -> Insights:
        """What the rules found, most urgent first, each explaining itself."""
        payload = self._request(
            "GET",
            f"{self._v1}/insights",
            params=_without_none({"period_start": period_start, "period_end": period_end}),
        )
        return Insights.from_json(payload)


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is None.

    An unset filter must be absent from the query string, not sent as an empty
    value — `?search=` is a search for the empty string, which is not the same
    request as not searching at all.
    """
    return {key: value for key, value in values.items() if value is not None}
