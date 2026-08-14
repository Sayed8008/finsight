"""Data access for users.

A *repository* is the only place that knows how a thing is stored. Services
call `users.get_by_email(...)` instead of writing `select(User).where(...)`
inline, which keeps query construction out of business logic and gives every
query about users one place to live — and one place to optimise.

Repositories do not commit. A service decides when a unit of work is
finished, because one business operation may touch several repositories and
must succeed or fail as a whole.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, user_id: int) -> User | None:
        return self._session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        """Look up a user by email, case-insensitively.

        Emails are stored lowercased, so a plain equality test is enough and
        the unique index is still used. Applying LOWER() to the column here
        would prevent the index from being used at all.
        """
        statement = select(User).where(User.email == email.strip().lower())
        return self._session.execute(statement).scalar_one_or_none()

    def email_exists(self, email: str) -> bool:
        statement = select(User.id).where(User.email == email.strip().lower())
        return self._session.execute(statement).first() is not None

    def add(self, user: User) -> User:
        """Stage a new user and assign its primary key.

        `flush` sends the INSERT so `user.id` is available to the caller, but
        does not commit — the surrounding transaction is still in charge.
        """
        self._session.add(user)
        self._session.flush()
        return user
