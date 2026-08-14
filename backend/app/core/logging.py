"""Logging configuration.

Configured once, at application startup. Application code should never call
`print()` or `logging.basicConfig()` — it should obtain a module-level logger
with `logging.getLogger(__name__)` and use that.

Rules for what may be logged are in docs/DECISIONS.md; in short: never log
passwords, tokens, or secrets, and do not log full financial records unless
there is a reason.
"""

from __future__ import annotations

import logging
import sys

_LOG_FORMAT = "%(asctime)s  %(levelname)-8s  %(name)-28s  %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str = "INFO") -> None:
    """Set up root logging for the process.

    Safe to call more than once: existing handlers are replaced rather than
    duplicated, which otherwise causes every message to be printed twice.
    """
    root = logging.getLogger()
    root.setLevel(level)

    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(handler)

    # Uvicorn installs its own handlers; let them propagate to ours instead so
    # all output shares one format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # SQLAlchemy's engine logger is very chatty at INFO.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
