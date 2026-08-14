"""Tests that the migrations and the models agree.

The failure this guards against is easy to cause and unpleasant to debug: a
column is added to a model, no migration is generated, everything passes
locally because the developer's database already has the column, and the
application breaks on a fresh database.
"""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect

from app.db.base import Base

EXPECTED_TABLES = {"users", "categories", "transactions", "budgets", "subscriptions"}


def test_all_expected_tables_exist(db_engine: Engine) -> None:
    tables = set(inspect(db_engine).get_table_names())

    assert EXPECTED_TABLES <= tables


def test_alembic_version_table_is_stamped(db_engine: Engine) -> None:
    """Proves the schema was built by migrations rather than create_all."""
    with db_engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()

    assert revision is not None


def test_models_match_the_migrated_schema(db_engine: Engine) -> None:
    """The migrated database must match the models exactly.

    `compare_metadata` returns the operations autogenerate *would* produce.
    An empty list means nothing has drifted; anything else means a model was
    changed without a corresponding migration.
    """
    with db_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == [], (
        "Models and migrations have diverged. Generate a migration with:\n"
        "    cd backend && ../.venv/bin/python -m alembic revision --autogenerate -m '...'\n"
        f"Differences: {differences}"
    )


def test_transaction_indexes_exist(db_engine: Engine) -> None:
    """The composite index serves list, date-filter and aggregate queries."""
    indexes = {index["name"] for index in inspect(db_engine).get_indexes("transactions")}

    assert "ix_transactions_user_date" in indexes
