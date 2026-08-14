"""Tests for the desktop client's shell and authentication flow.

These use pytest-qt, which provides the `qtbot` fixture: it creates the
QApplication, keeps widgets alive for the duration of a test, and cleans them
up afterwards.

The API client is replaced with a stub, so these tests never require a running
backend — they verify interface behaviour, not networking.
"""

from __future__ import annotations

import pytest

from client.api.client import ApiError, ApiUnavailableError
from client.api.dto import Token, User
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
