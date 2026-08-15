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
from client.views.analytics_view import AnalyticsView
from client.views.budgets_view import BudgetsView
from client.views.dashboard_view import DashboardView
from client.views.insights_view import InsightsView
from client.views.placeholder import PlaceholderView
from client.views.subscriptions_view import SubscriptionsView
from client.views.transactions_view import TransactionsView
from client.widgets.sidebar import NAV_ITEMS, Sidebar

logger = logging.getLogger(__name__)

#: Sections that have a real view. Anything not listed still gets a
#: placeholder, so adding a section to the sidebar cannot crash the shell.
TRANSACTIONS = "transactions"
BUDGETS = "budgets"
SUBSCRIPTIONS = "subscriptions"
DASHBOARD = "dashboard"
ANALYTICS = "analytics"
INSIGHTS = "insights"

# What each section will contain, shown until the real view is built.
SECTION_DESCRIPTIONS: dict[str, tuple[str, str]] = {
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
        self._display_name = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.navigated.connect(self._show_section)
        self.sidebar.sign_out_requested.connect(self.sign_out_requested.emit)
        layout.addWidget(self.sidebar)

        self.dashboard_view = DashboardView(api_client)
        self.dashboard_view.navigate_requested.connect(self.go_to)
        self.transactions_view = TransactionsView(api_client)
        self.budgets_view = BudgetsView(api_client)
        self.subscriptions_view = SubscriptionsView(api_client)
        self.analytics_view = AnalyticsView(api_client)
        self.insights_view = InsightsView(api_client)
        self.insights_view.navigate_requested.connect(self.go_to)

        self.pages = QStackedWidget()
        self.pages.setObjectName("ContentArea")
        self.page_index: dict[str, int] = {}
        for nav in NAV_ITEMS:
            self.page_index[nav.key] = self.pages.addWidget(self._page_for(nav.key))
        layout.addWidget(self.pages, stretch=1)

    def _page_for(self, key: str) -> QWidget:
        real_views: dict[str, QWidget] = {
            DASHBOARD: self.dashboard_view,
            TRANSACTIONS: self.transactions_view,
            BUDGETS: self.budgets_view,
            SUBSCRIPTIONS: self.subscriptions_view,
            ANALYTICS: self.analytics_view,
            INSIGHTS: self.insights_view,
        }
        if key in real_views:
            return real_views[key]
        title, message = SECTION_DESCRIPTIONS[key]
        return PlaceholderView(title, message)

    def show_user(self, user: User) -> None:
        self.sidebar.set_user(user.full_name, user.email)
        # The currency is per user, so amounts cannot be labelled until someone
        # is signed in.
        self._currency = user.currency_code
        self._display_name = user.full_name
        # The dashboard is the landing section, so it is already on screen when
        # this runs — it has to be told to load rather than waiting to be
        # navigated to.
        self.dashboard_view.load_once(self._currency, self._display_name)

    def go_to(self, key: str) -> None:
        """Open a section from somewhere other than the sidebar.

        Moves the sidebar selection too, so the highlighted item never
        disagrees with what is on screen.
        """
        for index, nav in enumerate(NAV_ITEMS):
            if nav.key == key:
                self.sidebar.select(index)
                return

    def _show_section(self, key: str) -> None:
        index = self.page_index.get(key)
        if index is None:
            return

        # Data is fetched when a section is first opened rather than at
        # construction: a user who stays on the dashboard should not pay for a
        # query they never look at.
        if key == DASHBOARD:
            self.dashboard_view.load_once(self._currency, self._display_name)
        elif key == TRANSACTIONS:
            self.transactions_view.load_once(self._currency)
        elif key == BUDGETS:
            self.budgets_view.load_once(self._currency)
        elif key == SUBSCRIPTIONS:
            self.subscriptions_view.load_once(self._currency)
        elif key == ANALYTICS:
            self.analytics_view.load_once(self._currency)
        elif key == INSIGHTS:
            self.insights_view.load_once(self._currency)

        self.pages.setCurrentIndex(index)
