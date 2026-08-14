"""The signed-in application: sidebar navigation and content area.

Holds no authentication logic. It is shown once a user is signed in and asks
the shell to end the session when the sidebar requests it.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QWidget

from client.api.client import ApiClient
from client.api.dto import User
from client.views.placeholder import PlaceholderView
from client.views.transactions_view import TransactionsView
from client.widgets.sidebar import NAV_ITEMS, Sidebar

logger = logging.getLogger(__name__)

#: Sections that have a real view. Anything not listed still gets a
#: placeholder, so adding a section to the sidebar cannot crash the shell.
TRANSACTIONS = "transactions"

# What each section will contain, shown until the real view is built.
SECTION_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "dashboard": (
        "Dashboard",
        "Balance, monthly summary, charts and insights will appear here.",
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

    def __init__(self, api_client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Root")
        self._api = api_client
        self._currency = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.navigated.connect(self._show_section)
        self.sidebar.sign_out_requested.connect(self.sign_out_requested.emit)
        layout.addWidget(self.sidebar)

        self.transactions_view = TransactionsView(api_client)

        self.pages = QStackedWidget()
        self.pages.setObjectName("ContentArea")
        self.page_index: dict[str, int] = {}
        for nav in NAV_ITEMS:
            self.page_index[nav.key] = self.pages.addWidget(self._page_for(nav.key))
        layout.addWidget(self.pages, stretch=1)

    def _page_for(self, key: str) -> QWidget:
        if key == TRANSACTIONS:
            return self.transactions_view
        title, message = SECTION_DESCRIPTIONS[key]
        return PlaceholderView(title, message)

    def show_user(self, user: User) -> None:
        self.sidebar.set_user(user.full_name, user.email)
        # The currency is per user, so amounts cannot be labelled until someone
        # is signed in.
        self._currency = user.currency_code

    def _show_section(self, key: str) -> None:
        index = self.page_index.get(key)
        if index is None:
            return

        # Data is fetched when a section is first opened rather than at
        # construction: a user who stays on the dashboard should not pay for a
        # query they never look at.
        if key == TRANSACTIONS:
            self.transactions_view.load_once(self._currency)

        self.pages.setCurrentIndex(index)
