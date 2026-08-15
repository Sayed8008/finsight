"""Desktop client entry point.

    python -m client.main            (from the frontend/ directory)
    python frontend/client/main.py   (from the project root)

Wires together configuration, logging, the API client and the main window,
then hands control to Qt's event loop.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

# Allow running this file directly, not only as a module.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.api.client import ApiClient  # noqa: E402
from client.core.config import ClientConfig  # noqa: E402
from client.views.main_window import MainWindow  # noqa: E402

logger = logging.getLogger(__name__)

RESOURCES_DIR = Path(__file__).resolve().parent / "resources"
STYLESHEET_PATH = RESOURCES_DIR / "style.qss"

#: Stands in for the resources directory inside the stylesheet. A stylesheet
#: `url(...)` is resolved against the process's working directory, which
#: depends on where the application was started from — so the path is filled in
#: here, where it is known, rather than being written in the sheet and working
#: only when launched from the right folder.
RESOURCES_TOKEN = "%RESOURCES%"


def load_stylesheet() -> str:
    """Read the application stylesheet, tolerating its absence.

    A missing stylesheet should leave an unstyled but working application,
    not prevent it from starting.

    Tests load the sheet through this function rather than reading the file, so
    that what they render is what the application renders. Reading it directly
    would leave the resource paths unsubstituted, and a missing image in Qt
    fails silently — the tests would show one thing and the user another, which
    is precisely what ADR-012 exists to stop.
    """
    try:
        sheet = STYLESHEET_PATH.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Stylesheet not found at %s; using default styling", STYLESHEET_PATH)
        return ""

    # `as_posix` because Qt wants forward slashes in a URL even on Windows.
    return sheet.replace(RESOURCES_TOKEN, RESOURCES_DIR.as_posix())


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)-28s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = ClientConfig.from_env()
    logger.info("Starting FinSight client (api=%s)", config.api_base_url)

    app = QApplication(sys.argv)
    app.setApplicationName("FinSight")
    app.setOrganizationName("FinSight")
    app.setStyleSheet(load_stylesheet())

    api_client = ApiClient(config)
    app.aboutToQuit.connect(api_client.close)

    window = MainWindow(api_client)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
