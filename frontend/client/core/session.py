"""Who is signed in, and notifying the interface when that changes.

One object owns authentication state. Widgets do not each keep their own copy
of the current user; they connect to the signals here and react. That is what
stops "log out" from having to remember every screen that needs clearing.

A Qt *signal* is a notification a widget emits; a *slot* is a function
connected to it. The emitter does not know or care who is listening, which is
what keeps these parts decoupled.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from client.api.client import ApiClient, ApiError
from client.api.dto import User

logger = logging.getLogger(__name__)


class Session(QObject):
    """Authentication state for the running application."""

    #: Emitted with the user after a successful sign-in.
    logged_in = Signal(object)
    #: Emitted after sign-out.
    logged_out = Signal()

    def __init__(self, api_client: ApiClient, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._api = api_client
        self._user: User | None = None

    @property
    def user(self) -> User | None:
        return self._user

    @property
    def is_authenticated(self) -> bool:
        return self._user is not None

    def log_in(self, email: str, password: str) -> User:
        """Sign in and remember the user. Raises `ApiError` on failure."""
        token = self._api.login(email, password)
        self._api.set_token(token.access_token)
        return self._adopt(self._api.me())

    def register(self, email: str, password: str, full_name: str) -> User:
        """Create an account and sign in with it. Raises `ApiError`."""
        token = self._api.register(email, password, full_name)
        self._api.set_token(token.access_token)
        return self._adopt(self._api.me())

    def log_out(self) -> None:
        """Sign out, discarding the token.

        The server is told, but an access token is stateless and cannot be
        revoked before it expires — discarding it here is what actually ends
        the session. A failure to reach the server must not prevent the user
        from logging out locally.
        """
        try:
            self._api.logout()
        except ApiError as exc:
            logger.info("Logout request failed, clearing local session anyway: %s", exc.message)

        self._api.set_token(None)
        self._user = None
        self.logged_out.emit()

    def _adopt(self, user: User) -> User:
        self._user = user
        logger.info("Signed in as user id=%s", user.id)
        self.logged_in.emit(user)
        return user
