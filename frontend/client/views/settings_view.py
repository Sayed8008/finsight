"""The settings screen: the account, and the categories everything else uses.

The last placeholder in the sidebar. The category endpoints have existed and
been tested since Phase 4; until now there was no way to reach them without an
HTTP client, which meant the one thing a user is most likely to want to
change — what their spending is grouped into — was the one thing they could not.

Two decisions from the server show up here as things the screen does rather than
things it explains:

  * **Retiring, not deleting** (ADR-020). There is no `DELETE /categories/{id}`,
    because the foreign key from `transactions.category_id` is `ON DELETE
    RESTRICT` and any category that has ever been used could not be removed
    anyway. So the button says "Retire", the confirmation says what that means,
    and retired categories stay on the screen — behind a toggle, dimmed, and
    restorable. A screen that hid them would make restoring one impossible.
  * **Changing anything here changes other screens.** Every view that offers a
    category picker holds its own list, fetched once. Without a signal, a
    category added here would be missing from the transactions filter until the
    application was restarted — so this screen says when something changed and
    the shell passes it on.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from client.api.client import ApiClient, ApiError
from client.api.dto import EXPENSE, INCOME, Category, User
from client.widgets.category_dialog import CategoryDialog
from client.widgets.forms import MessageBanner

logger = logging.getLogger(__name__)

#: The two groups, in the order they are shown. Money out first: it is what
#: most categories are and what most of the application is about.
GROUPS: tuple[tuple[str, str], ...] = (
    (EXPENSE, "Money out"),
    (INCOME, "Money in"),
)

#: Width every row action is given, so they line up down the list rather than
#: shifting with the length of their own labels.
ACTION_WIDTH = 84


class SettingsView(QWidget):
    """Account details, and the categories the rest of the app files things into."""

    #: Emitted when a category is created, renamed, retired or restored, so the
    #: shell can refresh the pickers on every other screen. The screens hold
    #: their own lists, fetched once; without this, a new category would be
    #: missing from them until the app restarted.
    categories_changed = Signal()

    def __init__(self, api_client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsView")
        self._api = api_client

        self._categories: list[Category] = []
        self._user: User | None = None
        self._loaded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setObjectName("DashboardScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        page = QWidget()
        page.setObjectName("DashboardPage")
        scroll.setWidget(page)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        layout.addLayout(self._build_header())

        self.banner = MessageBanner()
        layout.addWidget(self.banner)

        layout.addWidget(self._build_account_panel())
        layout.addWidget(self._build_categories_panel(), stretch=1)
        layout.addStretch(0)

    # ─── Construction ─────────────────────────────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        title = QLabel("Settings")
        title.setObjectName("SectionTitle")
        row.addWidget(title)

        row.addStretch(1)
        return row

    def _build_account_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("DashboardPanel")
        box = QVBoxLayout(panel)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(10)

        title = QLabel("Account")
        title.setObjectName("PanelTitle")
        box.addWidget(title)

        self.account_name = self._detail_row(box, "Name")
        self.account_email = self._detail_row(box, "Email")
        self.account_currency = self._detail_row(box, "Currency")

        note = QLabel(
            "These are fixed for now. Changing an email address means proving the new "
            "one belongs to you, and changing a currency means deciding what happens to "
            "every amount already recorded — neither is a field edit."
        )
        note.setObjectName("SettingsNote")
        note.setWordWrap(True)
        box.addWidget(note)

        return panel

    @staticmethod
    def _detail_row(box: QVBoxLayout, caption: str) -> QLabel:
        row = QHBoxLayout()
        row.setSpacing(10)

        label = QLabel(caption)
        label.setObjectName("SettingsCaption")
        label.setFixedWidth(90)
        row.addWidget(label)

        value = QLabel("—")
        value.setObjectName("SettingsValue")
        row.addWidget(value)
        row.addStretch(1)

        holder = QWidget()
        holder.setObjectName("FormRow")
        holder.setLayout(row)
        box.addWidget(holder)
        return value

    def _build_categories_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("DashboardPanel")
        box = QVBoxLayout(panel)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)

        title = QLabel("Categories")
        title.setObjectName("PanelTitle")
        header.addWidget(title)

        self.count_label = QLabel("")
        self.count_label.setObjectName("SectionSubtitle")
        header.addWidget(self.count_label)

        header.addStretch(1)

        self.show_retired = QCheckBox("Show retired")
        self.show_retired.setObjectName("FilterCheck")
        self.show_retired.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_retired.stateChanged.connect(self.reload)
        header.addWidget(self.show_retired)

        self.add_button = QPushButton("Add category")
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self.add_category)
        header.addWidget(self.add_button)

        box.addLayout(header)

        self._list_holder = QWidget()
        self._list_holder.setObjectName("CategoryList")
        self._list_layout = QVBoxLayout(self._list_holder)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch(1)
        box.addWidget(self._list_holder, stretch=1)

        self.empty_message = QLabel("")
        self.empty_message.setObjectName("EmptyMessage")
        self.empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_message.hide()
        box.addWidget(self.empty_message)

        return panel

    # ─── Loading ──────────────────────────────────────────────────────────

    def load_once(self, user: User | None = None) -> None:
        """Fetch the categories the first time this section is opened."""
        if user is not None:
            self._user = user
            self._render_account()
        if self._loaded:
            return
        self._loaded = True
        self.reload()

    def reload(self) -> None:
        try:
            self._categories = self._api.categories(
                include_inactive=self.show_retired.isChecked()
            )
        except ApiError as exc:
            self._show_error(exc)
            return

        self.banner.clear_message()
        self._render_categories()

    # ─── Rendering ────────────────────────────────────────────────────────

    def _render_account(self) -> None:
        user = self._user
        if user is None:
            return
        self.account_name.setText(user.full_name)
        self.account_email.setText(user.email)
        self.account_currency.setText(user.currency_code)

    def _render_categories(self) -> None:
        self._clear_list()

        active = [category for category in self._categories if category.is_active]
        self.count_label.setText(
            f"{len(active)} in use"
            + (
                f" · {len(self._categories) - len(active)} retired"
                if len(self._categories) > len(active)
                else ""
            )
        )

        shown = False
        for category_type, heading in GROUPS:
            group = [c for c in self._categories if c.category_type == category_type]
            if not group:
                continue
            shown = True
            self._insert(self._group_heading(heading))
            for category in sorted(group, key=lambda item: (not item.is_active, item.name)):
                self._insert(self._category_row(category))

        self.empty_message.setVisible(not shown)
        self._list_holder.setVisible(shown)
        if not shown:
            self.empty_message.setText(
                "No categories. Add one to start filing transactions into it."
            )

    def _insert(self, widget: QWidget) -> None:
        self._list_layout.insertWidget(self._list_layout.count() - 1, widget)

    def _clear_list(self) -> None:
        for index in reversed(range(self._list_layout.count())):
            widget = self._list_layout.itemAt(index).widget()
            if widget is not None:
                self._list_layout.takeAt(index)
                widget.setParent(None)
                widget.deleteLater()

    @staticmethod
    def _group_heading(text: str) -> QWidget:
        label = QLabel(text)
        label.setObjectName("CategoryGroup")
        return label

    def _category_row(self, category: Category) -> QWidget:
        row = QWidget()
        row.setObjectName("CategoryRow")
        row.setProperty("retired", "true" if not category.is_active else "false")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 7, 0, 7)
        layout.setSpacing(10)

        swatch = QLabel()
        swatch.setObjectName("CategorySwatch")
        swatch.setFixedSize(12, 12)
        if category.color:
            # Set per widget because the colour is data. A stylesheet rule
            # cannot know what colour a given category is.
            swatch.setStyleSheet(f"background-color: {category.color}; border-radius: 6px;")
        layout.addWidget(swatch)

        name = QLabel(category.name)
        name.setObjectName("CategoryName")
        name.setProperty("retired", "true" if not category.is_active else "false")
        layout.addWidget(name)

        if not category.is_active:
            badge = QLabel("retired")
            badge.setObjectName("CategoryBadge")
            layout.addWidget(badge)

        layout.addStretch(1)

        edit = QPushButton("Edit")
        edit.setObjectName("SecondaryButton")
        edit.setCursor(Qt.CursorShape.PointingHandCursor)
        edit.setMinimumWidth(ACTION_WIDTH)
        edit.clicked.connect(lambda _=False, item=category: self.edit_category(item))
        layout.addWidget(edit)

        if category.is_active:
            retire = QPushButton("Retire")
            retire.setObjectName("DangerButton")
            retire.setToolTip(
                "Stop offering this for new records. Nothing already filed under it "
                "is changed."
            )
            retire.clicked.connect(lambda _=False, item=category: self.retire_category(item))
        else:
            retire = QPushButton("Restore")
            retire.setObjectName("SecondaryButton")
            retire.clicked.connect(lambda _=False, item=category: self.restore_category(item))
        retire.setCursor(Qt.CursorShape.PointingHandCursor)
        # Both actions are the same width so the buttons form a column. Left to
        # size themselves, "Restore" is wider than "Retire" and every retired
        # row sits a few pixels out of line with the rest — visible as a ragged
        # edge down a list, and found by looking at one (ADR-012).
        retire.setMinimumWidth(ACTION_WIDTH)
        layout.addWidget(retire)

        return row

    # ─── Actions ──────────────────────────────────────────────────────────

    def add_category(self) -> None:
        dialog = CategoryDialog(
            save=lambda payload: self._api.create_category(**payload),
            parent=self,
        )
        if dialog.exec():
            self._after_change(f"Added {dialog.payload()['name']}.")

    def edit_category(self, category: Category) -> None:
        dialog = CategoryDialog(
            save=lambda payload: self._api.update_category(category.id, **payload),
            category=category,
            parent=self,
        )
        if dialog.exec():
            self._after_change(f"Updated {dialog.payload()['name']}.")

    def retire_category(self, category: Category) -> None:
        """Stop offering a category, without touching what is filed under it.

        Confirmed, and the confirmation says what retiring is *not*: there is no
        delete here (ADR-020), and somebody expecting one needs to know that the
        history stays exactly where it is.
        """
        answer = QMessageBox.question(
            self,
            "Retire category",
            f"Stop offering {category.name} for new transactions, budgets and "
            "subscriptions?\n\n"
            "Nothing already filed under it changes — this is not a delete, and it "
            "can be undone from this screen.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return

        if self._set_active(category, active=False):
            self._after_change(
                f"{category.name} retired. Turn on Show retired to bring it back."
            )

    def restore_category(self, category: Category) -> None:
        if self._set_active(category, active=True):
            self._after_change(f"{category.name} is available again.")

    def _set_active(self, category: Category, *, active: bool) -> bool:
        try:
            self._api.update_category(category.id, is_active=active)
        except ApiError as exc:
            logger.warning("Could not update category %s: %s", category.id, exc.message)
            self.banner.show_error(exc.message)
            return False
        return True

    def _after_change(self, message: str) -> None:
        """Refresh, tell the rest of the application, and say what happened.

        The message goes last because `reload` clears the banner on success,
        which would otherwise wipe the one line the user wants to read.
        """
        self.reload()
        self.categories_changed.emit()
        self.banner.show_info(message)

    # ─── Failure ──────────────────────────────────────────────────────────

    def _show_error(self, exc: ApiError) -> None:
        logger.warning("Settings request failed: %s", exc.message)
        self.banner.show_error(exc.message)
        self._categories = []
        self._clear_list()
        self._list_holder.setVisible(False)
        self.empty_message.setVisible(True)
        # Distinct from "there are none": one is a state of the account, the
        # other is a state of the connection, and they call for different acts.
        self.empty_message.setText(f"Could not load categories. {exc.message}")
        self.count_label.setText("")
