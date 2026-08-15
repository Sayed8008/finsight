"""Tests for the desktop client's shell and authentication flow.

These use pytest-qt, which provides the `qtbot` fixture: it creates the
QApplication, keeps widgets alive for the duration of a test, and cleans them
up afterwards.

The API client is replaced with a stub, so these tests never require a running
backend — they verify interface behaviour, not networking.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from client.api.client import ApiError, ApiUnavailableError
from client.api.dto import (
    Comparison,
    Dashboard,
    SavingsJourney,
    Token,
    TransactionPage,
    Trend,
    User,
)
from client.views.auth_view import LOGIN_PAGE, REGISTER_PAGE
from client.views.main_window import APP_PAGE, AUTH_PAGE, MainWindow
from client.widgets.sidebar import NAV_ITEMS

pytestmark = pytest.mark.gui

USER = User(
    id=1,
    email="sayed@example.com",
    full_name="Md. Abu Sayed",
    currency_code="BDT",
    role="user",
    is_active=True,
)
TOKEN = Token(access_token="a-token", token_type="bearer", expires_in=3600)


class StubApi:
    """An API client that succeeds, recording what it was asked to do."""

    def __init__(self) -> None:
        self.token: str | None = None
        self.calls: list[str] = []

    def health(self) -> dict[str, str]:
        return {"status": "ok"}

    def set_token(self, token: str | None) -> None:
        self.token = token

    def login(self, email: str, password: str) -> Token:
        self.calls.append("login")
        return TOKEN

    def register(self, email: str, password: str, full_name: str) -> Token:
        self.calls.append("register")
        return TOKEN

    def logout(self) -> None:
        self.calls.append("logout")

    def me(self) -> User:
        return USER

    def trend(self, **kwargs) -> Trend:
        """Navigating to Analytics fetches this; the shell tests only need a shape."""
        self.calls.append("trend")
        return Trend.empty()

    def comparison(self, **kwargs) -> Comparison:
        self.calls.append("comparison")
        return Comparison.empty()

    def savings(self, **kwargs) -> SavingsJourney:
        """Analytics fetches this too; the shell tests only need a shape."""
        self.calls.append("savings")
        return SavingsJourney.empty()

    def categories(self, **kwargs) -> list:
        """Fetched by Settings, and by every screen offering a category picker."""
        self.calls.append("categories")
        return []

    def payment_methods(self) -> list[str]:
        self.calls.append("payment_methods")
        return []

    def transactions(self, **kwargs):
        self.calls.append("transactions")
        return TransactionPage.empty(25)

    def dashboard(self, **kwargs) -> Dashboard:
        """Signing in lands on the dashboard, so the shell fetches it at once.

        An empty one is enough here: these tests are about the shell, not the
        dashboard's contents.
        """
        self.calls.append("dashboard")
        return Dashboard.empty()


class StubApiOffline(StubApi):
    def health(self) -> dict[str, str]:
        raise ApiUnavailableError("Cannot reach the FinSight backend. Is it running?")


class StubApiRejectsLogin(StubApi):
    def login(self, email: str, password: str) -> Token:
        raise ApiError("Incorrect email or password.", status_code=401)


def sign_in(window: MainWindow) -> None:
    window.auth_view._login_email.input.setText("sayed@example.com")
    window.auth_view._login_password.input.setText("a-good-enough-password")
    window.auth_view._submit_login()


@pytest.fixture
def window(qtbot) -> MainWindow:
    window = MainWindow(StubApi())
    qtbot.addWidget(window)
    return window


# ─── Shell ────────────────────────────────────────────────────────────────


def test_starts_on_the_authentication_screen(window: MainWindow) -> None:
    """An unauthenticated user must never see the application."""
    assert window.current_page() == AUTH_PAGE


def test_signing_in_reveals_the_application(window: MainWindow) -> None:
    sign_in(window)

    assert window.current_page() == APP_PAGE
    assert window.session.is_authenticated


def test_signing_in_shows_the_user_in_the_sidebar(window: MainWindow) -> None:
    sign_in(window)

    assert window.main_view.sidebar._account_name.text() == USER.full_name
    assert window.main_view.sidebar._account_email.text() == USER.email


def test_signing_out_returns_to_authentication(window: MainWindow) -> None:
    sign_in(window)

    window.session.log_out()

    assert window.current_page() == AUTH_PAGE
    assert not window.session.is_authenticated


def test_signing_out_clears_the_token(window: MainWindow) -> None:
    """The token is what grants access; discarding it is what ends the session."""
    sign_in(window)

    window.session.log_out()

    assert window._api.token is None


def test_sign_out_survives_an_unreachable_backend(qtbot) -> None:
    """A user must be able to sign out even when the server cannot be told."""

    class FailingLogout(StubApi):
        def logout(self) -> None:
            raise ApiUnavailableError("Cannot reach the FinSight backend.")

    window = MainWindow(FailingLogout())
    qtbot.addWidget(window)
    sign_in(window)

    window.session.log_out()

    assert window.current_page() == AUTH_PAGE
    assert window._api.token is None


# ─── The confirmation dialog, pressed for real ────────────────────────────
#
# Reported from manual testing: "Sign out" opened the dialog, "Yes" did
# nothing at all. Every test above calls `session.log_out()` directly, so the
# dialog — the only thing a user can actually reach — went unexercised, and
# the suite passed while the feature did not work.
#
# These press the real button in the real dialog, via the `answer_confirmation`
# fixture in conftest. Stubbing `QMessageBox.question` would not do: the bug
# *was* in what that function returns, so a stub inventing a return value would
# reproduce the false pass rather than the fault.


def test_confirming_the_dialog_actually_signs_out(window: MainWindow, answer_confirmation) -> None:
    """The bug: the dialog appeared, Yes was pressed, and nothing happened."""
    sign_in(window)

    asked = answer_confirmation(window._confirm_sign_out, "Yes")

    assert asked == "Sign out of FinSight?"
    assert window.current_page() == AUTH_PAGE
    assert not window.session.is_authenticated
    assert window._api.token is None
    assert "logout" in window._api.calls


def test_confirming_the_dialog_resets_the_screens(window: MainWindow, answer_confirmation) -> None:
    """Signing out through the dialog must clear as much as calling it directly."""
    sign_in(window)
    window.main_view.go_to("transactions")

    answer_confirmation(window._confirm_sign_out, "Yes")

    assert window.main_view._user is None
    assert window.main_view.transactions_view.is_loaded is False


def test_cancelling_the_dialog_leaves_the_user_signed_in(
    window: MainWindow, answer_confirmation
) -> None:
    """The other half of the fix: Cancel must not be treated as a yes."""
    sign_in(window)

    answer_confirmation(window._confirm_sign_out, "Cancel")

    assert window.current_page() == APP_PAGE
    assert window.session.is_authenticated
    assert window._api.token == TOKEN.access_token
    assert "logout" not in window._api.calls


# ─── Authentication view ──────────────────────────────────────────────────


def test_failed_login_shows_the_server_message_and_stays_put(qtbot) -> None:
    window = MainWindow(StubApiRejectsLogin())
    qtbot.addWidget(window)

    sign_in(window)

    assert window.current_page() == AUTH_PAGE
    assert window.auth_view._login_card.banner.text() == "Incorrect email or password."


def test_empty_login_is_reported_without_calling_the_api(window: MainWindow) -> None:
    window.auth_view._submit_login()

    assert window.current_page() == AUTH_PAGE
    assert "email and password" in window.auth_view._login_card.banner.text()
    assert window._api.calls == []


def test_short_password_is_rejected_before_calling_the_api(window: MainWindow) -> None:
    """Checked client-side for immediate feedback; the server still enforces it."""
    window.auth_view.show_register()
    window.auth_view._register_name.input.setText("Md. Abu Sayed")
    window.auth_view._register_email.input.setText("sayed@example.com")
    window.auth_view._register_password.input.setText("short")

    window.auth_view._submit_register()

    assert window._api.calls == []
    assert "at least 8" in window.auth_view._register_card.banner.text()


def test_registration_signs_the_user_in(window: MainWindow) -> None:
    window.auth_view.show_register()
    window.auth_view._register_name.input.setText("Md. Abu Sayed")
    window.auth_view._register_email.input.setText("sayed@example.com")
    window.auth_view._register_password.input.setText("a-good-enough-password")

    window.auth_view._submit_register()

    assert window.current_page() == APP_PAGE
    assert "register" in window._api.calls


def test_switching_between_login_and_register(window: MainWindow) -> None:
    assert window.auth_view.current_page() == LOGIN_PAGE

    window.auth_view.show_register()
    assert window.auth_view.current_page() == REGISTER_PAGE

    window.auth_view.show_login()
    assert window.auth_view.current_page() == LOGIN_PAGE


def test_password_field_is_masked(window: MainWindow) -> None:
    from PySide6.QtWidgets import QLineEdit

    assert window.auth_view._login_password.input.echoMode() == QLineEdit.EchoMode.Password


def test_password_is_cleared_after_signing_in(window: MainWindow) -> None:
    """No reason to keep the plaintext password in a widget after use."""
    sign_in(window)

    assert window.auth_view._login_password.text() == ""


# ─── Application view ─────────────────────────────────────────────────────


def test_a_page_exists_for_every_nav_item(window: MainWindow) -> None:
    assert window.main_view.pages.count() == len(NAV_ITEMS)


def test_navigation_switches_the_visible_page(window: MainWindow) -> None:
    assert window.main_view.pages.currentIndex() == 0

    window.main_view._show_section("analytics")

    assert window.main_view.pages.currentIndex() == window.main_view.page_index["analytics"]


# ─── Backend availability ─────────────────────────────────────────────────


def test_backend_check_succeeds_when_api_responds(window: MainWindow) -> None:
    assert window.check_backend() is True


def test_backend_check_fails_gracefully_when_api_is_down(qtbot) -> None:
    """An unreachable backend must not crash the client at startup."""
    window = MainWindow(StubApiOffline())
    qtbot.addWidget(window)

    assert window.check_backend() is False


# ─── Settings reaches the rest of the application ─────────────────────────


def test_settings_is_a_real_section_now(window: MainWindow) -> None:
    """The last placeholder in the sidebar."""
    sign_in(window)
    window.main_view.go_to("settings")

    from client.views.settings_view import SettingsView

    assert isinstance(window.main_view.pages.currentWidget(), SettingsView)


def test_changing_a_category_refreshes_the_pickers_that_are_open(window: MainWindow) -> None:
    """Each of those screens fetches its categories once, when first opened.
    Without this, a category added in Settings would be missing from the
    transactions filter until the application was restarted."""
    sign_in(window)
    window.main_view.go_to("transactions")
    api = window.main_view._api
    api.calls.clear()

    window.main_view.settings_view.categories_changed.emit()

    assert "categories" in api.calls


def test_a_screen_nobody_has_opened_is_not_woken_up(window: MainWindow) -> None:
    """Refreshing a picker on a section the user has never visited would make a
    request for a screen they may never look at."""
    sign_in(window)
    api = window.main_view._api
    api.calls.clear()

    window.main_view.settings_view.categories_changed.emit()

    assert api.calls == []


# ─── Signing out must not leave one user's data for the next ──────────────
#
# Reported from manual testing and reproduced against a live backend: Alice
# signed out, Bob signed in on the same window, and Alice's transactions were
# still on screen — under Bob's name in the sidebar. The widgets are built once
# and outlive a sign-out, so nothing was clearing them.


def test_signing_out_clears_the_screens(window: MainWindow) -> None:
    """The bug, at the level it actually happened."""
    sign_in(window)
    view = window.main_view
    view.go_to("transactions")
    assert view.transactions_view.is_loaded is True

    window.session.log_out()

    assert view.transactions_view.is_loaded is False
    assert view.transactions_view.model.rowCount() == 0
    assert view.dashboard_view._dashboard.totals.expense == Decimal("0.00")


def test_signing_out_forgets_who_was_signed_in(window: MainWindow) -> None:
    sign_in(window)

    window.session.log_out()

    assert window.main_view._user is None
    assert window.main_view._currency == ""


def test_signing_in_again_fetches_rather_than_reusing(window: MainWindow) -> None:
    """The mechanism behind the leak: every section was marked loaded, so the
    next session's navigation returned early and showed the old data."""
    sign_in(window)
    window.main_view.go_to("transactions")
    window.session.log_out()

    sign_in(window)
    api = window.main_view._api
    api.calls.clear()
    window.main_view.go_to("transactions")

    assert "transactions" in api.calls


def test_signing_out_returns_to_the_first_section(window: MainWindow) -> None:
    """Otherwise the next user lands wherever the last one happened to be."""
    sign_in(window)
    window.main_view.go_to("settings")

    window.session.log_out()

    assert window.main_view.sidebar.current_key() == "dashboard"


# ─── The dashboard must not show what was true an hour ago ────────────────


def test_opening_the_dashboard_refetches_it(window: MainWindow) -> None:
    """Reported from manual testing: a budget and transactions were added and
    the dashboard went on showing its opening figures. It fetched once per
    application run and never again."""
    sign_in(window)
    api = window.main_view._api
    window.main_view.go_to("transactions")
    api.calls.clear()

    window.main_view.go_to("dashboard")

    assert "dashboard" in api.calls
