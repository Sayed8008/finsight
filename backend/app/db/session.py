"""Database engine and session management.

Two objects matter here:

  * the **engine** owns the connection pool and is created once per process;
  * a **session** is a short-lived workspace for one unit of work — typically
    one HTTP request. It tracks the objects you have loaded or created and
    writes them out when you commit.

`get_db` is a FastAPI *dependency*: a function FastAPI calls to build an
argument for a route handler. Declaring `db: Session = Depends(get_db)` on a
route means FastAPI opens a session before the handler runs and closes it
afterwards, whether the handler succeeded or raised. Tests can substitute a
different session by overriding this one function.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def build_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create an engine with settings appropriate for MySQL."""
    return create_engine(
        database_url,
        echo=echo,
        # MySQL closes idle connections after `wait_timeout` (8 hours by
        # default). Without these two settings, a desktop app left open
        # overnight fails its next query with "MySQL server has gone away".
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=5,
        max_overflow=10,
    )


@lru_cache
def get_engine() -> Engine:
    """The application engine, created on first use and reused thereafter."""
    settings = get_settings()
    logger.info("Creating database engine for %s", _redact(settings.database_url))
    return build_engine(settings.database_url, echo=False)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Factory that produces new sessions bound to the application engine."""
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        # Keeps attribute values readable after commit(). Without this,
        # touching any attribute of a just-committed object triggers another
        # SELECT, which is a common and avoidable source of extra queries.
        expire_on_commit=False,
    )


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session for the current request."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def _redact(database_url: str) -> str:
    """Remove the password from a connection URL before logging it."""
    if "@" not in database_url or "://" not in database_url:
        return database_url
    scheme, _, rest = database_url.partition("://")
    credentials, _, host = rest.rpartition("@")
    user, _, _password = credentials.partition(":")
    return f"{scheme}://{user}:***@{host}"
