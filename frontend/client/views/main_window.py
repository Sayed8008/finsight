"""Application main window.

Owns the window chrome and navigation. Each section's content is a separate
view; this class only decides which one is visible. No business logic and no
HTTP calls belong here — it asks `ApiClient` and displays the result.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from client.api.client import ApiClient, ApiError
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


class MainWindow(QMainWindow):
    """The main application window."""

    def __init__(self, api_client: ApiClient, parent=None) -> None:
        super().__init__(parent)
        self._api = api_client

        self.setWindowTitle("FinSight")
        self.resize(1180, 760)
        self.setMinimumSize(940, 600)

        container = QWidget()
        container.setObjectName("Root")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._sidebar = Sidebar()
        self._sidebar.navigated.connect(self._show_section)
        layout.addWidget(self._sidebar)

        self._pages = QStackedWidget()
        self._pages.setObjectName("ContentArea")
        self._page_index: dict[str, int] = {}
        for nav in NAV_ITEMS:
            title, message = SECTION_DESCRIPTIONS[nav.key]
            index = self._pages.addWidget(PlaceholderView(title, message))
            self._page_index[nav.key] = index
        layout.addWidget(self._pages, stretch=1)

        self.setCentralWidget(container)

        self.check_backend()

    def _show_section(self, key: str) -> None:
        index = self._page_index.get(key)
        if index is not None:
            self._pages.setCurrentIndex(index)

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
            self._sidebar.set_backend_status(online=False)
            return False

        self._sidebar.set_backend_status(online=True)
        return True
