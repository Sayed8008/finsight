"""Sign-in and registration screen.

The view collects input and displays results. It performs no validation rules
of its own beyond "these boxes are not empty" and holds no knowledge of how
authentication works — it calls `Session` and reports what comes back.

Everything here is deliberately synchronous. Signing in involves one request
to a local server, where the slowest part is the deliberate cost of password
hashing — around a tenth of a second. Moving that onto a worker thread would
add real complexity for an unnoticeable gain. It is worth revisiting only if
the backend is ever remote.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from client.api.client import ApiError, ApiUnavailableError
from client.core.session import Session
from client.widgets.forms import FormField, MessageBanner

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 8

LOGIN_PAGE = 0
REGISTER_PAGE = 1


class _AuthCard(QFrame):
    """Shared chrome for the two forms: a centred card with a heading."""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AuthCard")
        self.setFixedWidth(400)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(36, 36, 36, 36)
        self._layout.setSpacing(16)

        heading = QLabel(title)
        heading.setObjectName("AuthTitle")
        self._layout.addWidget(heading)

        caption = QLabel(subtitle)
        caption.setObjectName("AuthSubtitle")
        caption.setWordWrap(True)
        self._layout.addWidget(caption)

        self.banner = MessageBanner()
        self._layout.addWidget(self.banner)

    def add(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)


class AuthView(QWidget):
    """Login and registration, switchable between the two."""

    #: Emitted once the user is signed in, so the shell can show the app.
    authenticated = Signal()

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AuthView")
        self._session = session

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_login())
        self._pages.addWidget(self._build_register())

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._pages, alignment=Qt.AlignmentFlag.AlignCenter)

    # ─── Construction ─────────────────────────────────────────────────────

    def _build_login(self) -> QWidget:
        card = _AuthCard("Sign in to FinSight", "Track spending, budgets and subscriptions.")
        self._login_card = card

        self._login_email = FormField("Email", placeholder="you@example.com")
        self._login_password = FormField("Password", placeholder="Your password", password=True)
        card.add(self._login_email)
        card.add(self._login_password)

        self._login_button = QPushButton("Sign in")
        self._login_button.setObjectName("PrimaryButton")
        self._login_button.setDefault(True)
        self._login_button.clicked.connect(self._submit_login)
        card.add(self._login_button)

        card.add(self._switch_row("New here?", "Create an account", self.show_register))

        # Enter submits from either field.
        self._login_email.input.returnPressed.connect(self._submit_login)
        self._login_password.input.returnPressed.connect(self._submit_login)

        return card

    def _build_register(self) -> QWidget:
        card = _AuthCard(
            "Create your account", "It takes a moment. Your data stays on your machine."
        )
        self._register_card = card

        self._register_name = FormField("Full name", placeholder="Md. Abu Sayed")
        self._register_email = FormField("Email", placeholder="you@example.com")
        self._register_password = FormField(
            "Password", placeholder=f"At least {MIN_PASSWORD_LENGTH} characters", password=True
        )
        card.add(self._register_name)
        card.add(self._register_email)
        card.add(self._register_password)

        self._register_button = QPushButton("Create account")
        self._register_button.setObjectName("PrimaryButton")
        self._register_button.clicked.connect(self._submit_register)
        card.add(self._register_button)

        card.add(self._switch_row("Already registered?", "Sign in", self.show_login))

        for field in (self._register_name, self._register_email, self._register_password):
            field.input.returnPressed.connect(self._submit_register)

        return card

    def _switch_row(self, prompt: str, action: str, handler) -> QWidget:
        row = QWidget()
        # Needs its own object name so the stylesheet can make it transparent;
        # otherwise it inherits the page background and shows as a grey band
        # inside the white card.
        row.setObjectName("AuthSwitchRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        label = QLabel(prompt)
        label.setObjectName("AuthSwitchPrompt")
        layout.addWidget(label)

        button = QPushButton(action)
        button.setObjectName("LinkButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(handler)
        layout.addWidget(button)

        return row

    # ─── Navigation ───────────────────────────────────────────────────────

    def show_login(self) -> None:
        self._login_card.banner.clear_message()
        self._pages.setCurrentIndex(LOGIN_PAGE)
        self._login_email.input.setFocus()

    def show_register(self) -> None:
        self._register_card.banner.clear_message()
        self._pages.setCurrentIndex(REGISTER_PAGE)
        self._register_name.input.setFocus()

    def current_page(self) -> int:
        return self._pages.currentIndex()

    # ─── Submission ───────────────────────────────────────────────────────

    def _submit_login(self) -> None:
        email = self._login_email.text().strip()
        password = self._login_password.text()

        if not email or not password:
            self._login_card.banner.show_error("Enter your email and password.")
            return

        self._set_busy(self._login_button, busy=True, label="Signing in…")
        try:
            self._session.log_in(email, password)
        except ApiUnavailableError as exc:
            self._login_card.banner.show_error(exc.message)
        except ApiError as exc:
            self._login_card.banner.show_error(exc.message)
        else:
            self._login_password.clear()
            self._login_card.banner.clear_message()
            self.authenticated.emit()
        finally:
            self._set_busy(self._login_button, busy=False, label="Sign in")

    def _submit_register(self) -> None:
        name = self._register_name.text().strip()
        email = self._register_email.text().strip()
        password = self._register_password.text()

        # Checked here as well as on the server, so the user is told
        # immediately rather than after a round trip. The server remains the
        # authority — a client is never trusted to enforce a rule.
        if not name or not email or not password:
            self._register_card.banner.show_error("Please fill in every field.")
            return
        if len(password) < MIN_PASSWORD_LENGTH:
            self._register_card.banner.show_error(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
            )
            return

        self._set_busy(self._register_button, busy=True, label="Creating account…")
        try:
            self._session.register(email, password, name)
        except ApiUnavailableError as exc:
            self._register_card.banner.show_error(exc.message)
        except ApiError as exc:
            self._register_card.banner.show_error(exc.message)
        else:
            self._register_password.clear()
            self._register_card.banner.clear_message()
            self.authenticated.emit()
        finally:
            self._set_busy(self._register_button, busy=False, label="Create account")

    def _set_busy(self, button: QPushButton, *, busy: bool, label: str) -> None:
        """Show that work is in progress and prevent a second submission."""
        button.setEnabled(not busy)
        button.setText(label)
        # Repaint now: the request that follows blocks the event loop, so
        # without this the new label would never appear on screen.
        button.repaint()

    def reset(self) -> None:
        """Clear both forms. Called after signing out."""
        for field in (
            self._login_email,
            self._login_password,
            self._register_name,
            self._register_email,
            self._register_password,
        ):
            field.clear()
        self._login_card.banner.clear_message()
        self._register_card.banner.clear_message()
        self.show_login()
