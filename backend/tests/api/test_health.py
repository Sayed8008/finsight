"""Tests for the health endpoint.

These are deliberately the first tests in the project: they prove the test
harness itself works — app construction, settings injection, and HTTP
round-trips — before any real feature depends on it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "finsight-api",
        "version": "0.1.0",
    }


def test_unknown_route_returns_404(client: TestClient) -> None:
    """A missing route must produce a clean 404, not a server error."""
    response = client.get("/no-such-endpoint")

    assert response.status_code == 404


def test_openapi_schema_is_available(client: TestClient) -> None:
    """The OpenAPI document backs the /docs page shown during the demo."""
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "FinSight API"
