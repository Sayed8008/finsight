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

from PySide6.QtGui import QIcon
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

#: The application logo, in the order it is looked for. A PNG dropped in beside
#: the SVG wins, so replacing the logo is copying a file rather than editing
#: code — and the fallback means a missing or deleted logo leaves a working
#: application with Qt's default icon rather than no application at all.
ICON_NAMES = ("finsight.png", "finsight.svg")


def app_icon() -> QIcon:
    """The window and taskbar icon, or an empty one if none is installed.

    Without this the window carries Qt's generic icon, which is what the
    taskbar, the alt-tab switcher and the "about" dialog all show — the
    desktop entry's icon only covers the launcher.
    """
    for name in ICON_NAMES:
        candidate = RESOURCES_DIR / name
        if candidate.is_file():
            return QIcon(str(candidate))
    logger.warning("No application icon found in %s", RESOURCES_DIR)
    return QIcon()


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
    # Set on the application, so every window and dialog inherits it.
    app.setWindowIcon(app_icon())
    app.setStyleSheet(load_stylesheet())

    api_client = ApiClient(config)
    app.aboutToQuit.connect(api_client.close)

    window = MainWindow(api_client)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
