"""Sidebar navigation.

A presentation-only widget: it knows which sections exist and which one is
selected, and emits a signal when that changes. It knows nothing about what
those sections contain.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt, Signal
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

from client.core.animation import FAST_MS, animate_geometry


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
    NavItem("insights", "Insights"),
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

        # A bar that travels between items rather than a highlight that blinks
        # from one to the next. Parented to the list's viewport so it scrolls
        # and clips with the items, and given no mouse handling at all — an
        # indicator that swallowed a click would make the item under it
        # unselectable.
        self._indicator = QFrame(self._list.viewport())
        self._indicator.setObjectName("NavIndicator")
        self._indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._indicator.setFixedWidth(3)
        self._list.currentRowChanged.connect(self._move_indicator)

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
        panel_layout.setContentsMargins(16, 14, 16, 14)
        panel_layout.setSpacing(2)

        self._account_name = QLabel("")
        self._account_name.setObjectName("AccountName")
        panel_layout.addWidget(self._account_name)

        self._account_email = QLabel("")
        self._account_email.setObjectName("AccountEmail")
        panel_layout.addWidget(self._account_email)

        # A button, not a link. As a bare blue label directly beneath the email
        # it read as a third line of account text rather than as an action —
        # nothing about it said it could be pressed, and it was easy to miss
        # and easy to hit by accident. Everything else the user can do in this
        # application is a bordered button, so this is one too.
        panel_layout.addSpacing(10)
        self._sign_out_button = QPushButton("Sign out")
        self._sign_out_button.setObjectName("SignOutButton")
        self._sign_out_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sign_out_button.setToolTip("End this session and return to the sign-in screen")
        self._sign_out_button.clicked.connect(self.sign_out_requested.emit)
        panel_layout.addWidget(self._sign_out_button)

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

    def _move_indicator(self, row: int | None = None) -> None:
        """Slide the indicator to the selected item.

        Driven off the item's own rectangle rather than a computed row height,
        so it stays aligned if the padding in the stylesheet changes.
        """
        current = self._list.currentRow() if row is None else row
        item = self._list.item(current)
        if item is None:
            return
        rect = self._list.visualItemRect(item)
        if not rect.isValid():
            return
        # Inset vertically so the bar is shorter than the row — a full-height
        # bar reads as a border on the panel rather than as a marker.
        inset = 6
        animate_geometry(
            self._indicator,
            QRect(2, rect.top() + inset, 3, max(rect.height() - inset * 2, 1)),
            FAST_MS,
        )

    def showEvent(self, event) -> None:  # noqa: N802  (Qt naming)
        """Place the indicator once the list has a real geometry.

        `visualItemRect` returns an empty rectangle before the widget has been
        laid out, so this cannot be done in `__init__`.
        """
        super().showEvent(event)
        self._move_indicator()

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

    def select(self, row: int) -> None:
        """Move the selection, as if the user had clicked it.

        Needed because the dashboard links onward to other sections. Setting
        the page directly would leave the sidebar highlighting one section
        while a different one is on screen.
        """
        if 0 <= row < len(NAV_ITEMS):
            self._list.setCurrentRow(row)
