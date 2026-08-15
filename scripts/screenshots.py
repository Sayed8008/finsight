#!/usr/bin/env python
"""Capture a screenshot of every section, for the README and the report.

    ./scripts/dev.sh backend                       # in one terminal
    .venv/bin/python scripts/seed_demo.py          # once
    .venv/bin/python scripts/screenshots.py

Writes PNGs into `docs/screenshots/`.

**Rendered offscreen, against the real backend.** These are not mock-ups: the
script signs the demo account in through the real API client and drives the real
views, so a screenshot cannot show a screen the application does not produce.
That is the same practice ADR-012 established for finding layout defects — it
has caught one in every interface phase — pointed at documentation instead.

`QT_QPA_PLATFORM=offscreen` is set here rather than being required of the
caller, since the whole point is that this needs no display.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "frontend"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from client.api.client import ApiClient, ApiError  # noqa: E402
from client.main import load_stylesheet  # noqa: E402
from client.views.main_window import MainWindow  # noqa: E402
from client.widgets.detection_dialog import DetectionDialog  # noqa: E402
from client.widgets.sidebar import NAV_ITEMS  # noqa: E402

OUTPUT_DIR = PROJECT_ROOT / "docs" / "screenshots"

DEFAULT_EMAIL = "demo@finsight.app"
DEFAULT_PASSWORD = "demo-account-password"

#: Large enough that nothing is cramped, small enough to read in a document.
WINDOW_SIZE = (1280, 820)


def capture(widget, path: Path) -> None:
    QApplication.processEvents()
    widget.grab().save(str(path))
    print(f"  {path.relative_to(PROJECT_ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    arguments = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv)
    app.setStyleSheet(load_stylesheet())

    api = ApiClient()
    try:
        api.health()
    except ApiError as exc:
        print(f"{exc.message}\nStart it with: ./scripts/dev.sh backend", file=sys.stderr)
        return 1

    window = MainWindow(api)
    window.resize(*WINDOW_SIZE)
    window.show()

    # The sign-in screen is worth a picture of its own, before anything is
    # filled in — it is the first thing anybody sees.
    capture(window, OUTPUT_DIR / "00-sign-in.png")

    window.auth_view._login_email.input.setText(arguments.email)
    window.auth_view._login_password.input.setText(arguments.password)
    window.auth_view._submit_login()

    if not api.is_authenticated:
        print(
            f"Could not sign in as {arguments.email}. "
            "Run scripts/seed_demo.py first.",
            file=sys.stderr,
        )
        return 1

    for index, item in enumerate(NAV_ITEMS):
        window.main_view.sidebar.select(index)
        capture(window, OUTPUT_DIR / f"{index + 1:02d}-{item.key}.png")

    # The two dialogs that carry the features worth showing. Both are built
    # here rather than clicked, so the capture does not depend on a modal event
    # loop that would never return without a user.
    detection = api.detect_subscriptions()
    dialog = DetectionDialog(detection, track=lambda candidate: None, currency="BDT")
    dialog.resize(760, 620)
    dialog.show()
    capture(dialog, OUTPUT_DIR / "08-find-subscriptions.png")

    api.close()
    print(f"\nWrote {len(NAV_ITEMS) + 2} screenshots to {OUTPUT_DIR.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
