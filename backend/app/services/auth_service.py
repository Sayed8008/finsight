"""Registration and login.

The *service layer* holds business logic: the rules of the application, free
of HTTP and free of SQL. Routes translate HTTP into calls here; repositories
translate these calls into queries. That separation is what lets registration
be tested by calling a function, with no web server involved.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.default_categories import DEFAULT_CATEGORIES
from app.core.exceptions import EmailAlreadyRegistered, InactiveAccount, InvalidCredentials
from app.core.security import (
    create_access_token,
    hash_password,
    password_needs_rehash,
    verify_password,
    waste_time_like_a_failed_verification,
)
from app.models.category import Category
from app.models.user import User
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)

    # ─── Registration ─────────────────────────────────────────────────────

    def register(self, email: str, password: str, full_name: str) -> User:
        """Create an account, along with its starting set of categories.

        Registration and category seeding happen in one transaction. A user
        with no categories could not record a single transaction, so a
        half-finished registration is worse than none at all.
        """
        normalised_email = email.strip().lower()

        if self._users.email_exists(normalised_email):
            raise EmailAlreadyRegistered

        user = User(
            email=normalised_email,
            password_hash=hash_password(password),
            full_name=full_name.strip(),
            currency_code=self._settings.default_currency,
        )

        try:
            self._users.add(user)
            self._seed_categories(user)
            self._session.commit()
        except IntegrityError:
            # Two registrations for the same email can pass the check above
            # concurrently; the unique index is what actually decides. This
            # turns that race into the same clean error as the common case.
            self._session.rollback()
            raise EmailAlreadyRegistered from None

        logger.info("Registered new account id=%s", user.id)
        return user

    def _seed_categories(self, user: User) -> None:
        self._session.add_all(
            Category(
                user_id=user.id,
                name=default.name,
                category_type=default.category_type,
                color=default.color,
            )
            for default in DEFAULT_CATEGORIES
        )
        self._session.flush()

    # ─── Login ────────────────────────────────────────────────────────────

    def authenticate(self, email: str, password: str) -> User:
        """Verify credentials and return the user.

        Raises `InvalidCredentials` for both an unknown email and a wrong
        password, with the same message and comparable timing, so the
        response cannot be used to discover which accounts exist.
        """
        user = self._users.get_by_email(email)

        if user is None:
            waste_time_like_a_failed_verification()
            logger.info("Login failed: no account for the submitted email")
            raise InvalidCredentials

        if not verify_password(password, user.password_hash):
            logger.info("Login failed: wrong password for user id=%s", user.id)
            raise InvalidCredentials

        if not user.is_active:
            logger.info("Login refused: account id=%s is deactivated", user.id)
            raise InactiveAccount

        # Cost parameters can be raised over time; a correct login is the only
        # moment the plaintext is available to re-hash with.
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
            self._session.commit()
            logger.info("Upgraded password hash parameters for user id=%s", user.id)

        logger.info("Login succeeded for user id=%s", user.id)
        return user

    def issue_token(self, user: User) -> tuple[str, int]:
        """Create an access token for an authenticated user."""
        return create_access_token(user.id, self._settings)
