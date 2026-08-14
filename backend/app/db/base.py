"""Declarative base and shared model conventions.

Every ORM model inherits from `Base`, which is what lets SQLAlchemy — and
Alembic — discover the full schema from one object.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Explicit names for indexes and constraints.
#
# Left to itself, a database invents names for constraints, and they differ
# between engines. Alembic then generates migrations that try to drop
# constraints by names that do not match, which fails in confusing ways. Fixing
# the pattern up front means every constraint has a predictable name.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    """Current UTC time, without a timezone attached.

    MySQL's DATETIME type stores no timezone information. Rather than let the
    server's local timezone decide what a stored value means, every timestamp
    in this application is UTC, and that is recorded here in one place.
    Conversion to the user's local time is the interface's job.
    """
    return datetime.now(UTC).replace(tzinfo=None)


class TimestampMixin:
    """Adds `created_at` and `updated_at` to a model.

    Defaults are applied by Python rather than the database so that the values
    are identical regardless of the database server's clock or timezone, and
    so they are populated on the object immediately after a flush.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
