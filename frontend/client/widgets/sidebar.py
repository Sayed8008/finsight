"""Sidebar navigation.

A presentation-only widget: it knows which sections exist and which one is
selected, and emits a signal when that changes. It knows nothing about what
those sections contain.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class NavItem:
    """One entry in the sidebar."""

    key: str
    label: str


NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem("dashboard", "Dashboard"),
    NavItem("transactions", "Transactions"),
    NavItem("budgets", "Budgets"),
    NavItem("subscriptions", "Subscriptions"),
    NavItem("analytics", "Analytics"),
    NavItem("settings", "Settings"),
)


class Sidebar(QFrame):
    """Vertical navigation rail.

    Emits `navigated` with the key of the newly selected section.
    """

    navigated = Signal(str)
    #: Emitted when the user asks to sign out. The sidebar does not act on it
    #: itself — ending a session is the shell's responsibility, not a widget's.
    sign_out_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(216)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        wordmark = QLabel("FinSight")
        wordmark.setObjectName("Wordmark")
        wordmark.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(wordmark)

        self._list = QListWidget()
        self._list.setObjectName("NavList")
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for item in NAV_ITEMS:
            entry = QListWidgetItem(item.label)
            entry.setData(Qt.ItemDataRole.UserRole, item.key)
            self._list.addItem(entry)
        self._list.setCurrentRow(0)
        self._list.currentRowChanged.connect(self._on_row_changed)

        # The nav list must show every item. Left to its own devices inside a
        # layout with a stretch below it, Qt gives the list a small height and
        # scrolls the remaining entries out of sight.
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setFixedHeight(self._natural_list_height())
        layout.addWidget(self._list)

        layout.addStretch(1)

        layout.addWidget(self._build_account_panel())

        self._status = QLabel("Not connected")
        self._status.setObjectName("SidebarStatus")
        layout.addWidget(self._status)

    def _build_account_panel(self) -> QWidget:
        """Who is signed in, and the way out."""
        panel = QWidget()
        panel.setObjectName("AccountPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 14, 20, 12)
        panel_layout.setSpacing(2)

        self._account_name = QLabel("")
        self._account_name.setObjectName("AccountName")
        panel_layout.addWidget(self._account_name)

        self._account_email = QLabel("")
        self._account_email.setObjectName("AccountEmail")
        panel_layout.addWidget(self._account_email)

        self._sign_out_button = QPushButton("Sign out")
        self._sign_out_button.setObjectName("LinkButton")
        self._sign_out_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sign_out_button.clicked.connect(self.sign_out_requested.emit)
        panel_layout.addWidget(self._sign_out_button, alignment=Qt.AlignmentFlag.AlignLeft)

        return panel

    def set_user(self, full_name: str, email: str) -> None:
        """Show the signed-in account in the sidebar footer."""
        self._account_name.setText(full_name)
        self._account_email.setText(email)

    def _natural_list_height(self) -> int:
        """Height needed to display every navigation item without scrolling."""
        row_margin = 2  # matches `#NavList::item { margin: 1px 0 }` in style.qss
        list_padding = 8  # matches `#NavList { padding: 4px 10px }`
        rows = sum(self._list.sizeHintForRow(row) + row_margin for row in range(self._list.count()))
        return rows + list_padding

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(NAV_ITEMS):
            self.navigated.emit(NAV_ITEMS[row].key)

    def set_backend_status(self, *, online: bool, detail: str = "") -> None:
        """Show whether the API is reachable.

        Called by the main window after its health check, so the user learns
        the backend is down from the interface rather than from a failed
        action later on.
        """
        self._status.setText(detail or ("Connected" if online else "Backend offline"))
        self._status.setProperty("online", "true" if online else "false")
        # Qt only re-applies stylesheet rules when the style is refreshed.
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    def current_key(self) -> str:
        return NAV_ITEMS[self._list.currentRow()].key
