"""Shared pytest fixtures for the backend test suite.

A *fixture* is a named piece of setup that pytest supplies to any test that
asks for it by parameter name. It replaces copy-pasted setup code and makes it
obvious what each test depends on.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Settings used by tests.

    Constructed explicitly rather than read from `.env`, so the suite behaves
    the same on every machine and cannot accidentally talk to a real database.
    """
    return Settings(
        debug=True,
        log_level="WARNING",
        secret_key="test-only-key-not-used-outside-the-test-suite",
    )


@pytest.fixture
def client(test_settings: Settings) -> Iterator[TestClient]:
    """An HTTP client wired directly to a fresh application instance.

    `TestClient` is httpx driving the ASGI app in-process — no server is
    started and no network port is used, so tests are fast and cannot collide
    with a running development server.
    """
    app = create_app(test_settings)
    with TestClient(app) as test_client:
        yield test_client
