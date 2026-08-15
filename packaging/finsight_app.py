"""Entry point for the bundled application: API and window in one process.

The development launcher starts two processes and a terminal. A person given a
single file expects to double-click it, so this runs the API on a background
thread inside the same process and then hands the main thread to Qt.

**Why a thread rather than a subprocess.** A frozen build has no `python` to
re-invoke — `sys.executable` is the bundle itself, so spawning "the backend"
would relaunch the whole application. A thread also dies with the process,
which is the behaviour wanted: closing the window ends the API, with no
orphaned server left listening.

**Qt owns the main thread.** Qt requires it, so uvicorn gets the background
one. Nothing is shared between them but the socket: the client talks to the
API over HTTP exactly as it does in development, so the bundle exercises the
same code path rather than a special one that only exists when frozen.

MySQL is still required, and deliberately so — the analytics layer depends on
its date functions and `GROUP BY` semantics (ADR-005). This bundle removes the
need for Python, a virtual environment and a terminal; it does not remove the
database.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

#: Where the bundle keeps its own files. PyInstaller unpacks to a temporary
#: directory and points `sys._MEIPASS` at it; running from source, this file's
#: parent is the project.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

#: The folder the executable itself sits in — where a user would reasonably
#: put a `.env` next to the application, and not the same place as `BUNDLE_DIR`.
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parents[1]

HOST = "127.0.0.1"
PORT = 8000
API_URL = f"http://{HOST}:{PORT}"

#: How long to wait for the API before giving up and saying so. Generous
#: because a cold MySQL on a laptop that has just booted is not instant.
STARTUP_TIMEOUT_S = 30


def _load_configuration() -> Path | None:
    """Find the `.env` and make the settings loader read it.

    Looked for beside the executable first, because that is where somebody
    given a single file will put it. Falls back to the working directory so
    running the bundle from a checkout behaves as it always did.
    """
    for candidate in (APP_DIR / ".env", Path.cwd() / ".env"):
        if candidate.is_file():
            os.environ.setdefault("FINSIGHT_ENV_FILE", str(candidate))
            # Pydantic Settings reads `.env` relative to the process's working
            # directory, which for a double-clicked application is not the
            # folder the application is in.
            os.chdir(candidate.parent)
            return candidate
    return None


def _serve_api(ready: threading.Event, failed: list[BaseException]) -> None:
    """Run uvicorn until the process ends."""
    try:
        import uvicorn

        from app.main import app

        config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
        server = uvicorn.Server(config)
        # Signal handlers can only be installed on the main thread, and Qt has
        # it. Without this uvicorn raises on startup in a frozen build.
        server.install_signal_handlers = lambda: None
        ready.set()
        server.run()
    except BaseException as exc:  # noqa: BLE001 — reported to the user below
        failed.append(exc)
        ready.set()


def _wait_for_api() -> bool:
    import httpx

    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{API_URL}/health", timeout=1.0).status_code == 200:
                return True
        except Exception:  # noqa: BLE001 — not up yet is the normal case
            pass
        time.sleep(0.25)
    return False


def _report(message: str) -> None:
    """Tell the user something went wrong, in a window rather than a console.

    A bundled application launched from a file manager has nowhere to print.
    """
    print(f"FinSight: {message}", file=sys.stderr)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        # A QApplication has to exist before any widget can be shown, and at
        # this point one may not — the failure may be that the API never came
        # up, long before the client was reached. Qt owns the instance once
        # constructed, so it does not need holding here.
        if QApplication.instance() is None:
            QApplication(sys.argv)
        QMessageBox.critical(None, "FinSight", message)
    except Exception:  # noqa: BLE001 — Qt itself may be what failed
        pass


def main() -> int:
    env_file = _load_configuration()
    if env_file is None:
        _report(
            "No configuration file found.\n\n"
            f"FinSight needs a .env file beside the application:\n{APP_DIR / '.env'}\n\n"
            "It must set SECRET_KEY and DATABASE_URL. See the README."
        )
        return 1

    ready = threading.Event()
    failed: list[BaseException] = []
    # A daemon thread, so closing the window ends the API rather than leaving
    # the process alive with no window.
    threading.Thread(target=_serve_api, args=(ready, failed), daemon=True).start()
    ready.wait(timeout=5)

    if failed:
        _report(f"The FinSight API could not start.\n\n{failed[0]}")
        return 1

    if not _wait_for_api():
        _report(
            "The FinSight API did not become ready.\n\n"
            "The usual cause is MySQL not running, or the wrong DATABASE_URL "
            f"in {env_file}."
        )
        return 1

    from client.main import main as run_client

    return run_client()


if __name__ == "__main__":
    raise SystemExit(main())
