"""Reviewing a CSV file before any of it is imported.

The interface half of the rule the service enforces: **preview, then commit**.
Nothing here can import a file that has not been read back to the user first,
because the import needs the fingerprint the preview returned, and the button
that sends it stays disabled until there is one.

Three things follow from that, and each is a deliberate detail rather than a
side effect:

  * **Changing any option puts the button back to disabled.** A preview
    describes a file read a particular way. Once the date order changes it
    describes nothing, and a button that stayed live would import a set of rows
    nobody looked at.
  * **A blocked file still shows its whole report.** The blockers are the
    reason the user is here; hiding the rest behind them would leave them with
    a refusal and no way to act on it.
  * **The permissive options are on this screen, not behind it.** "Create the
    categories" and "import the readable rows" are offered next to the count of
    exactly what they would do — which is the difference between a choice and a
    shrug.

The sample table earns its place: seeing `2026-03-04` come back out of
`04/03/2026` is how somebody catches the wrong date order in two seconds
instead of six months.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from client.api.client import ApiClient, ApiError
from client.api.dto import (
    CREATE,
    DATE_ORDER_LABELS,
    DAY_FIRST,
    ISO_DATES,
    MONTH_FIRST,
    REFUSE,
    Category,
    CategoryPlan,
    ImportPreview,
    ImportResult,
    PreviewRow,
)
from client.widgets.forms import LabelledWidget, MessageBanner

logger = logging.getLogger(__name__)

#: How many of anything to list before saying "and N more". The server already
#: samples; this is the second guard, so a report cannot become the file again.
LIST_LIMIT = 10

DATE_ORDERS: tuple[tuple[str, str], ...] = (
    (DATE_ORDER_LABELS[ISO_DATES], ISO_DATES),
    (DATE_ORDER_LABELS[DAY_FIRST], DAY_FIRST),
    (DATE_ORDER_LABELS[MONTH_FIRST], MONTH_FIRST),
)

UNKNOWN_CATEGORY_CHOICES: tuple[tuple[str, str], ...] = (
    ("Stop and let me fix the file", REFUSE),
    ("Create them as I import", CREATE),
)

SAMPLE_COLUMNS = ("Line", "Date", "Amount", "Direction", "Category", "Description")


class ImportDialog(QDialog):
    """Check a file, then import exactly what was checked."""

    def __init__(
        self,
        content: bytes,
        *,
        api_client: ApiClient,
        filename: str = "transactions.csv",
        categories: Sequence[Category] = (),
        currency: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._content = content
        self._filename = filename
        self._categories = list(categories)
        self._currency = currency

        #: The last preview, or None if the file has not been checked yet.
        self.preview: ImportPreview | None = None
        #: What the import did, once it has. The caller reads this rather than
        #: being told through a signal — the dialog is modal and returns.
        self.result: ImportResult | None = None
        #: Set when an option changes after a preview, because the preview then
        #: describes a reading of the file that is no longer the chosen one.
        self._stale = False

        self.setWindowTitle("Import transactions")
        self.setObjectName("ImportDialog")
        self.setModal(True)
        self.setMinimumSize(760, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_options())

        self.banner = MessageBanner()
        layout.addWidget(self.banner)

        layout.addWidget(self._build_report(), stretch=1)
        layout.addLayout(self._build_buttons())

        self._render_report()
        self._update_buttons()

    # ─── Construction ─────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("FormRow")
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)

        title = QLabel("Import transactions")
        title.setObjectName("AuthTitle")
        box.addWidget(title)

        self.subtitle_label = QLabel(
            f"{self._filename} · nothing is written until you have checked it."
        )
        self.subtitle_label.setObjectName("AuthSubtitle")
        self.subtitle_label.setWordWrap(True)
        box.addWidget(self.subtitle_label)

        return panel

    def _build_options(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("FilterBar")
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(12)

        first = QHBoxLayout()
        first.setSpacing(12)

        self.date_order = self._select(DATE_ORDERS)
        self.date_order.setToolTip(
            "03/04/2026 is two different days depending on where the file came from, "
            "so this is asked rather than guessed."
        )
        first.addWidget(LabelledWidget("Dates in this file", self.date_order), stretch=2)

        self.unknown_categories = self._select(UNKNOWN_CATEGORY_CHOICES)
        first.addWidget(
            LabelledWidget("Categories I do not have", self.unknown_categories), stretch=2
        )

        self.default_category = self._select(
            (("Use the file's own", None), *((c.name, c.id) for c in self._categories))
        )
        self.default_category.setToolTip(
            "Where to file rows with no category. Also what makes a file with no "
            "category column importable at all."
        )
        first.addWidget(LabelledWidget("Rows without one", self.default_category), stretch=2)

        outer.addLayout(first)

        second = QHBoxLayout()
        second.setSpacing(16)

        self.skip_duplicates = QCheckBox("Leave out rows already recorded")
        self.skip_duplicates.setObjectName("FilterCheck")
        self.skip_duplicates.setChecked(True)
        self.skip_duplicates.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skip_duplicates.stateChanged.connect(self._on_option_changed)
        second.addWidget(self.skip_duplicates)

        self.skip_invalid = QCheckBox("Import the readable rows and leave the rest")
        self.skip_invalid.setObjectName("FilterCheck")
        self.skip_invalid.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skip_invalid.stateChanged.connect(self._on_option_changed)
        second.addWidget(self.skip_invalid)

        second.addStretch(1)

        self.check_button = QPushButton("Check the file")
        self.check_button.setObjectName("SecondaryButton")
        self.check_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_button.clicked.connect(self.check_file)
        second.addWidget(self.check_button)

        outer.addLayout(second)
        return bar

    def _select(self, entries: Sequence[tuple[str, object]]) -> QComboBox:
        box = QComboBox()
        box.setObjectName("FieldSelect")
        for label, value in entries:
            box.addItem(label, value)
        box.currentIndexChanged.connect(self._on_option_changed)
        return box

    def _build_report(self) -> QWidget:
        self._holder = QWidget()
        self._holder.setObjectName("CardHolder")
        self._holder_layout = QVBoxLayout(self._holder)
        self._holder_layout.setContentsMargins(0, 0, 0, 0)
        self._holder_layout.setSpacing(10)
        self._holder_layout.addStretch(1)

        area = QScrollArea()
        area.setObjectName("CardScroll")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(self._holder)
        return area

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("SecondaryButton")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self.reject)
        row.addWidget(self.cancel_button)

        self.import_button = QPushButton("Import")
        self.import_button.setObjectName("PrimaryButton")
        self.import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_button.clicked.connect(self.run_import)
        row.addWidget(self.import_button)

        return row

    # ─── Options ──────────────────────────────────────────────────────────

    def options(self) -> dict[str, object]:
        """The chosen options, as the API client takes them."""
        return {
            "date_order": self.date_order.currentData(),
            "unknown_categories": self.unknown_categories.currentData(),
            "default_category_id": self.default_category.currentData(),
            "skip_duplicates": self.skip_duplicates.isChecked(),
            "skip_invalid": self.skip_invalid.isChecked(),
        }

    def _on_option_changed(self) -> None:
        """An option moved, so the last preview no longer describes anything.

        The server would refuse the import anyway — the fingerprint covers the
        options — but being refused after pressing Import is a worse way to
        learn this than the button going quiet.
        """
        if self.preview is not None:
            self._stale = True
            self.banner.show_info("Options changed — check the file again before importing.")
            self._render_report()
        self._update_buttons()

    # ─── Actions ──────────────────────────────────────────────────────────

    def check_file(self) -> None:
        """Ask what importing this file would do. Creates nothing."""
        try:
            preview = self._api.preview_import(
                self._content, filename=self._filename, **self.options()
            )
        except ApiError as exc:
            logger.warning("Could not read %s: %s", self._filename, exc.message)
            self.preview = None
            self._stale = False
            self.banner.show_error(exc.message)
            self._render_report()
            self._update_buttons()
            return

        self.preview = preview
        self._stale = False
        self.banner.clear_message()
        self._render_report()
        self._update_buttons()

    def run_import(self) -> None:
        """Import exactly what was checked, and close.

        Guarded rather than merely disabled: a disabled button is an interface
        detail, and this method is also reachable from a keyboard default and
        from a test.
        """
        if self.preview is None or self._stale or not self.preview.can_import:
            self.banner.show_error("Check the file first.")
            return

        try:
            self.result = self._api.import_transactions(
                self._content,
                digest=self.preview.digest,
                filename=self._filename,
                **self.options(),
            )
        except ApiError as exc:
            logger.warning("Could not import %s: %s", self._filename, exc.message)
            self.banner.show_error(exc.message)
            # The preview is dropped: whatever the server refused, this one no
            # longer describes what would happen.
            self._stale = True
            self._update_buttons()
            return

        self.accept()

    def _update_buttons(self) -> None:
        ready = self.preview is not None and not self._stale and self.preview.can_import
        self.import_button.setEnabled(ready)

        if ready and self.preview is not None:
            count = self.preview.would_import
            self.import_button.setText(
                f"Import {count} transaction{'s' if count != 1 else ''}"
            )
        else:
            self.import_button.setText("Import")

    # ─── Rendering the report ─────────────────────────────────────────────

    def _render_report(self) -> None:
        self._clear()

        if self.preview is None:
            self._add(
                self._note_card(
                    "Nothing has been read yet",
                    "Choose how this file writes its dates, then press Check the file. "
                    "Checking reads the file and reports what would happen; it writes nothing.",
                )
            )
            return

        preview = self.preview

        if self._stale:
            # Found by rendering the dialog and reading it (ADR-012): with the
            # report left as it was, a changed date order left "412 of 418 rows
            # would be imported" on screen describing a reading nobody had
            # chosen. The banner said so; the largest number on the page did
            # not. The report is kept rather than cleared — it is still useful
            # for comparison — but it is no longer allowed to look current.
            self._add(
                self._stale_card(
                    "This report is out of date",
                    "It was made with the options as they were. Press Check the file "
                    "again to see what would happen now.",
                )
            )

        self._add(self._summary_card(preview))

        for blocker in preview.blockers:
            self._add(self._blocker_card(blocker))

        if preview.categories:
            self._add(self._categories_card(preview.categories))

        if preview.problems:
            self._add(self._problems_card(preview))

        if preview.duplicates:
            self._add(self._duplicates_card(preview))

        if preview.sample:
            self._add(self._sample_card(preview.sample))

    def _add(self, card: QWidget) -> None:
        self._holder_layout.insertWidget(self._holder_layout.count() - 1, card)

    def _clear(self) -> None:
        for index in reversed(range(self._holder_layout.count())):
            widget = self._holder_layout.itemAt(index).widget()
            if widget is not None:
                self._holder_layout.takeAt(index)
                widget.setParent(None)
                widget.deleteLater()

    @staticmethod
    def _card(name: str = "ReportCard") -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName(name)
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(6)
        return card, box

    @staticmethod
    def _title(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("ReportTitle")
        return label

    @staticmethod
    def _line(text: str, *, muted: bool = False) -> QLabel:
        label = QLabel(text)
        label.setObjectName("ReportMuted" if muted else "ReportLine")
        label.setWordWrap(True)
        return label

    def _note_card(self, title: str, message: str) -> QWidget:
        card, box = self._card()
        box.addWidget(self._title(title))
        box.addWidget(self._line(message, muted=True))
        return card

    def _stale_card(self, title: str, message: str) -> QWidget:
        card, box = self._card("StaleCard")

        heading = QLabel(title)
        heading.setObjectName("StaleTitle")
        box.addWidget(heading)

        detail = QLabel(message)
        detail.setObjectName("StaleText")
        detail.setWordWrap(True)
        box.addWidget(detail)

        return card

    def _summary_card(self, preview: ImportPreview) -> QWidget:
        card, box = self._card()
        box.addWidget(
            self._title(
                f"{preview.would_import} of {preview.total_rows} row"
                f"{'s' if preview.total_rows != 1 else ''} would be imported"
            )
        )

        counts: list[str] = []
        if preview.failed_rows:
            counts.append(f"{preview.failed_rows} could not be read")
        if preview.duplicate_rows:
            counts.append(f"{preview.duplicate_rows} already recorded")
        if counts:
            box.addWidget(self._line(" · ".join(counts)))

        notes = [f"Columns recognised: {', '.join(preview.columns) or 'none'}."]
        if preview.ambiguous_dates:
            notes.append(
                f"{preview.ambiguous_dates} date(s) would read as a different day the "
                "other way round — the sample below shows how they were taken."
            )
        if preview.encoding != "utf-8-sig":
            notes.append(f"Read as {preview.encoding} rather than UTF-8.")
        box.addWidget(self._line(" ".join(notes), muted=True))

        return card

    def _blocker_card(self, blocker: str) -> QWidget:
        card, box = self._card("BlockerCard")
        label = QLabel(blocker)
        label.setObjectName("BlockerText")
        label.setWordWrap(True)
        box.addWidget(label)
        return card

    def _categories_card(self, categories: Sequence[CategoryPlan]) -> QWidget:
        card, box = self._card()
        box.addWidget(self._title("Categories in this file"))

        for plan in categories[:LIST_LIMIT]:
            row = QHBoxLayout()
            row.setSpacing(8)

            name = QLabel(plan.name)
            name.setObjectName("ReportLine")
            row.addWidget(name)

            badge = QLabel(plan.action_label)
            badge.setObjectName("ReportBadge")
            badge.setProperty("settled", "true" if plan.is_settled else "false")
            row.addWidget(badge)

            row.addStretch(1)

            count = QLabel(f"{plan.rows} row{'s' if plan.rows != 1 else ''}")
            count.setObjectName("ReportMuted")
            row.addWidget(count)

            holder = QWidget()
            holder.setObjectName("FormRow")
            holder.setLayout(row)
            box.addWidget(holder)

        if len(categories) > LIST_LIMIT:
            box.addWidget(self._line(f"and {len(categories) - LIST_LIMIT} more.", muted=True))

        return card

    def _problems_card(self, preview: ImportPreview) -> QWidget:
        card, box = self._card()
        box.addWidget(self._title(f"{preview.failed_rows} row(s) could not be read"))

        for problem in preview.problems[:LIST_LIMIT]:
            box.addWidget(
                self._line(f"Line {problem.line_number} · {problem.column} — {problem.message}")
            )

        if preview.failed_rows > len(preview.problems):
            box.addWidget(self._line("Correct these and check the file again.", muted=True))

        return card

    def _duplicates_card(self, preview: ImportPreview) -> QWidget:
        card, box = self._card()
        box.addWidget(self._title(f"{preview.duplicate_rows} row(s) already recorded"))

        for duplicate in preview.duplicates[:LIST_LIMIT]:
            box.addWidget(
                self._line(
                    f"Line {duplicate.line_number} · {duplicate.date:%d %b %Y} · "
                    f"{self._money(duplicate.amount)} · {duplicate.description} "
                    f"({duplicate.source_label})"
                )
            )

        return card

    def _sample_card(self, sample: Sequence[PreviewRow]) -> QWidget:
        card, box = self._card()
        box.addWidget(self._title("How the first rows were read"))
        box.addWidget(
            self._line(
                "Check the dates and amounts here before importing — this is what "
                "would be written.",
                muted=True,
            )
        )

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)

        for column, heading in enumerate(SAMPLE_COLUMNS):
            label = QLabel(heading)
            label.setObjectName("SampleHeader")
            grid.addWidget(label, 0, column)

        for index, row in enumerate(sample, start=1):
            cells = (
                str(row.line_number),
                f"{row.date:%d %b %Y}",
                self._money(row.amount),
                "in" if row.is_income else "out",
                row.category_name or "—",
                row.description or "—",
            )
            for column, text in enumerate(cells):
                cell = QLabel(text)
                cell.setObjectName("SampleCell")
                grid.addWidget(cell, index, column)

        grid.setColumnStretch(len(SAMPLE_COLUMNS) - 1, 1)

        holder = QWidget()
        holder.setObjectName("FormRow")
        holder.setLayout(grid)
        box.addWidget(holder)

        return card

    def _money(self, value: Decimal) -> str:
        return f"{value:,.2f} {self._currency}".strip()
