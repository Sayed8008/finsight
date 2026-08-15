"""Application shell.

Owns the window and decides which of two things is on screen: the
authentication view, or the signed-in application. Keeping that decision in
one place means no other widget has to ask whether someone is logged in.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QMainWindow, QStackedWidget, QWidget

from client.api.client import ApiClient, ApiError
from client.core.session import Session
from client.views.auth_view import AuthView
from client.views.main_view import MainView
from client.widgets.confirm import confirm

logger = logging.getLogger(__name__)

AUTH_PAGE = 0
APP_PAGE = 1


class MainWindow(QMainWindow):
    """The main application window."""

    def __init__(self, api_client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api_client
        self.session = Session(api_client, parent=self)

        self.setWindowTitle("FinSight")
        self.resize(1180, 760)
        self.setMinimumSize(940, 600)

        self.auth_view = AuthView(self.session)
        self.auth_view.authenticated.connect(self._show_application)

        self.main_view = MainView(api_client)
        self.main_view.sign_out_requested.connect(self._confirm_sign_out)

        self._pages = QStackedWidget()
        self._pages.addWidget(self.auth_view)
        self._pages.addWidget(self.main_view)
        self.setCentralWidget(self._pages)

        self.session.logged_in.connect(self.main_view.show_user)
        # Cleared before the screen is swapped, so nothing belonging to the
        # session that just ended is still in the widgets when the next person
        # signs in. Connected here rather than done inside `_show_authentication`
        # because that also runs at startup, when there is nothing to clear.
        self.session.logged_out.connect(self.main_view.reset)
        self.session.logged_out.connect(self._show_authentication)

        self._show_authentication()
        self.check_backend()

    # ─── Screen switching ─────────────────────────────────────────────────

    def _show_authentication(self) -> None:
        self._pages.setCurrentIndex(AUTH_PAGE)
        self.auth_view.reset()

    def _show_application(self) -> None:
        self._pages.setCurrentIndex(APP_PAGE)
        self.check_backend()

    def current_page(self) -> int:
        return self._pages.currentIndex()

    # ─── Sign out ─────────────────────────────────────────────────────────

    def _confirm_sign_out(self) -> None:
        """Ask before signing out.

        Signing out is not destructive, but it is disruptive and easy to click
        by accident, so it gets a confirmation like any other action the user
        cannot undo with one click.
        """
        if confirm(self, "Sign out", "Sign out of FinSight?"):
            self.session.log_out()

    # ─── Backend status ───────────────────────────────────────────────────

    def check_backend(self) -> bool:
        """Ask the API whether it is running and reflect that in the sidebar.

        Returns True if the backend responded. Called at startup so the user
        is told the backend is down immediately, rather than discovering it
        when their first action fails.
        """
        try:
            self._api.health()
        except ApiError as exc:
            logger.warning("Backend health check failed: %s", exc.message)
            self.main_view.sidebar.set_backend_status(online=False)
            return False

        self.main_view.sidebar.set_backend_status(online=True)
        return True
