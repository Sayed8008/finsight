"""The signed-in application: sidebar navigation and content area.

Holds no authentication logic. It is shown once a user is signed in and asks
the shell to end the session when the sidebar requests it.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QWidget

from client.api.dto import User
from client.views.placeholder import PlaceholderView
from client.widgets.sidebar import NAV_ITEMS, Sidebar

logger = logging.getLogger(__name__)

# What each section will contain, shown until the real view is built.
SECTION_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "dashboard": (
        "Dashboard",
        "Balance, monthly summary, charts and insights will appear here.",
    ),
    "transactions": (
        "Transactions",
        "Your income and expenses, with filtering, search and CSV import.",
    ),
    "budgets": (
        "Budgets",
        "Monthly budgets per category, with spend tracking and alerts.",
    ),
    "subscriptions": (
        "Subscriptions",
        "Recurring payments, renewal dates and total monthly commitment.",
    ),
    "analytics": (
        "Analytics",
        "Spending trends and category comparisons over a chosen period.",
    ),
    "settings": (
        "Settings",
        "Account details, categories and application preferences.",
    ),
}


class MainView(QWidget):
    """Sidebar plus content area, shown to a signed-in user."""

    sign_out_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Root")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.navigated.connect(self._show_section)
        self.sidebar.sign_out_requested.connect(self.sign_out_requested.emit)
        layout.addWidget(self.sidebar)

        self.pages = QStackedWidget()
        self.pages.setObjectName("ContentArea")
        self.page_index: dict[str, int] = {}
        for nav in NAV_ITEMS:
            title, message = SECTION_DESCRIPTIONS[nav.key]
            self.page_index[nav.key] = self.pages.addWidget(PlaceholderView(title, message))
        layout.addWidget(self.pages, stretch=1)

    def show_user(self, user: User) -> None:
        self.sidebar.set_user(user.full_name, user.email)

    def _show_section(self, key: str) -> None:
        index = self.page_index.get(key)
        if index is not None:
            self.pages.setCurrentIndex(index)
