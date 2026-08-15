"""Application exceptions.

Services raise these; the API layer turns them into HTTP responses. Keeping
them free of HTTP details is what allows the service layer to be tested
without a web framework, and stops `HTTPException` from spreading into
business logic where it does not belong.

Each carries a message written for a user. Technical detail goes to the log,
not to the client — an error response should never disclose whether an email
is registered, what a query looked like, or where the code failed.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for expected, handled failures.

    `status_code` is the HTTP status the API layer will use. It lives here
    rather than in each route so that one mapping serves every endpoint.

    `headers` is for the rare status whose meaning is incomplete without one —
    a 429 without `Retry-After` tells a client to back off for an unknown
    length of time, which it can only answer by guessing.
    """

    status_code: int = 400
    message: str = "The request could not be completed."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.__class__.message
        self.headers: dict[str, str] = {}
        super().__init__(self.message)


class ValidationFailed(AppError):
    """Input was well-formed but not acceptable."""

    status_code = 422
    message = "The submitted data is not valid."


class NotFound(AppError):
    """A requested resource does not exist, or is not this user's to see.

    Deliberately does not distinguish the two. Replying "not found" for
    another user's record, rather than "forbidden", avoids confirming that
    the record exists at all.
    """

    status_code = 404
    message = "The requested item was not found."


class Conflict(AppError):
    """The request conflicts with the current state of the data."""

    status_code = 409
    message = "That conflicts with something that already exists."


class EmailAlreadyRegistered(Conflict):
    message = "An account with that email address already exists."


class AuthenticationFailed(AppError):
    """Credentials were missing, wrong, or expired."""

    status_code = 401
    message = "Could not authenticate. Please sign in again."


class InvalidCredentials(AuthenticationFailed):
    # Identical whether the email is unknown or the password is wrong, so the
    # response cannot be used to discover which accounts exist.
    message = "Incorrect email or password."


class InactiveAccount(AuthenticationFailed):
    message = "This account has been deactivated."


class PermissionDenied(AppError):
    """The user is authenticated but not allowed to do this."""

    status_code = 403
    message = "You do not have permission to do that."


class TooManyAttempts(AppError):
    """The caller has been refused for making too many attempts too quickly.

    Says how long to wait, in the message and in `Retry-After`. Deliberately
    identical whether or not the email exists, for the same reason failed
    logins are (ADR-018) — a throttle that only fires for real accounts is a
    way of finding out which accounts are real.
    """

    status_code = 429
    message = "Too many attempts. Please wait a moment and try again."

    def __init__(self, retry_after_seconds: int) -> None:
        wait = max(1, retry_after_seconds)
        minutes, seconds = divmod(wait, 60)
        spoken = f"{minutes} minute{'s' if minutes != 1 else ''}" if minutes else f"{seconds}s"
        super().__init__(f"Too many attempts. Please try again in about {spoken}.")
        self.retry_after_seconds = wait
        self.headers = {"Retry-After": str(wait)}
