"""Shared pytest fixtures for the backend test suite.

A *fixture* is a named piece of setup that pytest supplies to any test that
asks for it by parameter name. It replaces copy-pasted setup code and makes it
obvious what each test depends on.

Database tests run against `finsight_test`, never the development database
(ADR-005). The schema is built by running the real Alembic migrations, so a
broken migration fails the suite rather than being discovered later.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine, get_db
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Settings used by tests.

    Values not given explicitly still come from `.env`, which is where the
    test database URL lives.
    """
    return Settings(
        debug=True,
        log_level="WARNING",
        secret_key="test-only-key-not-used-outside-the-test-suite",
    )


@pytest.fixture(scope="session")
def db_engine(test_settings: Settings) -> Iterator[Engine]:
    """An engine pointed at the test database, with the schema applied.

    The schema is dropped and rebuilt once per session, by running Alembic
    rather than `create_all`. That way the migrations themselves are exercised
    on every test run, instead of only the models.
    """
    url = test_settings.test_database_url
    if "finsight_test" not in url:
        pytest.fail(
            f"Refusing to run: TEST_DATABASE_URL does not point at finsight_test ({url!r}). "
            "These tests destroy data."
        )

    engine = build_engine(url)

    # Start from nothing. FOREIGN_KEY_CHECKS is disabled so tables can be
    # dropped without first sorting them by dependency order.
    with engine.begin() as connection:
        connection.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in Base.metadata.sorted_tables:
            connection.execute(text(f"DROP TABLE IF EXISTS `{table.name}`"))
        connection.execute(text("DROP TABLE IF EXISTS `alembic_version`"))
        connection.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    # Equivalent to `alembic -x db_url=... upgrade head`; see alembic/env.py.
    config.cmd_opts = SimpleNamespace(x=[f"db_url={url}"])
    command.upgrade(config, "head")

    yield engine

    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session whose changes are discarded when the test finishes.

    Each test runs inside a transaction that is rolled back afterwards, so
    tests cannot see one another's data and the database needs no cleanup
    between them. `join_transaction_mode="create_savepoint"` means a
    `commit()` in the code under test releases a savepoint rather than ending
    this outer transaction.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(test_settings: Settings, db_session: Session) -> Iterator[TestClient]:
    """An HTTP client wired to a fresh app instance and the test database.

    `TestClient` is httpx driving the ASGI app in-process — no server is
    started and no network port is used, so tests are fast and cannot collide
    with a running development server.

    `dependency_overrides` replaces `get_db`, so route handlers receive the
    rolled-back test session instead of opening their own. This is the
    practical payoff of injecting the session as a dependency rather than
    importing it directly.
    """
    app = create_app(test_settings)
    app.dependency_overrides[get_db] = lambda: db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


# ─── Registered accounts ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Account:
    """A registered user, with what a test needs to act as them."""

    id: int
    email: str
    password: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


DEFAULT_PASSWORD = "a-good-enough-password"


@pytest.fixture
def make_account(client: TestClient) -> Callable[..., Account]:
    """Factory: register an account and return it signed in.

    A factory rather than a plain fixture because the interesting tests need
    *two* accounts — every endpoint is checked to answer 404, not 403 or 200,
    when handed another user's row id.
    """

    def _make(
        email: str = "sayed@example.com",
        full_name: str = "Md. Abu Sayed",
        password: str = DEFAULT_PASSWORD,
    ) -> Account:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": full_name},
        )
        assert response.status_code == 201, response.text
        token = response.json()["access_token"]

        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200, me.text

        return Account(id=me.json()["id"], email=email, password=password, token=token)

    return _make


@pytest.fixture
def account(make_account: Callable[..., Account]) -> Account:
    """The user a test acts as."""
    return make_account()


@pytest.fixture
def other_account(make_account: Callable[..., Account]) -> Account:
    """A second user, whose data the first must never be able to reach."""
    return make_account(email="intruder@example.com", full_name="Someone Else")
