"""Alembic migration environment.

Alembic keeps the database schema in version control. Each change to the
models produces a migration file describing how to move the database forward
(and back), so every machine — yours, a teammate's, a marker's — can reach the
same schema by running the same ordered steps. Tables are never altered by
hand (ADR: see docs/DECISIONS.md).

Two details differ from the file Alembic generates by default:

  * the connection URL is read from application settings rather than
    `alembic.ini`, so the database password lives only in `.env` and never in
    a file that git tracks;
  * `target_metadata` points at the models' metadata, which is what lets
    `alembic revision --autogenerate` diff the models against the database.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Importing the models package registers every model on Base.metadata.
# Without this import, autogenerate would see an empty schema and helpfully
# offer to drop all your tables.
import app.models  # noqa: F401  (imported for its side effect)
from app.core.config import get_settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    """Connection URL for migrations.

    `-x db_url=...` on the command line wins, which is how the test suite
    points migrations at the test database:

        alembic -x db_url=mysql+pymysql://... upgrade head
    """
    overrides = context.get_x_argument(as_dictionary=True)
    if "db_url" in overrides:
        return overrides["db_url"]
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it against a database.

    Useful for reviewing exactly what a migration will do, or handing the SQL
    to someone who controls the database directly.
    """
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    # NullPool: a migration run is short-lived and uses a single connection,
    # so there is nothing to gain from keeping a pool around afterwards.
    connectable = create_engine(get_database_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detect column type changes, not just added/removed columns.
            # Off by default, and its absence is a common reason a migration
            # silently misses a change.
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
