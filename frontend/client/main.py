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

STYLESHEET_PATH = Path(__file__).resolve().parent / "resources" / "style.qss"


def load_stylesheet() -> str:
    """Read the application stylesheet, tolerating its absence.

    A missing stylesheet should leave an unstyled but working application,
    not prevent it from starting.
    """
    try:
        return STYLESHEET_PATH.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Stylesheet not found at %s; using default styling", STYLESHEET_PATH)
        return ""


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
