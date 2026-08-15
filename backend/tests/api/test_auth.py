"""End-to-end tests for the authentication endpoints."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.default_categories import DEFAULT_CATEGORIES
from app.db.session import get_db
from app.main import create_app
from app.models import Category, User

REGISTRATION = {
    "email": "sayed@example.com",
    "password": "a-good-enough-password",
    "full_name": "Md. Abu Sayed",
}


def register(client: TestClient, **overrides: object) -> dict:
    response = client.post("/api/v1/auth/register", json={**REGISTRATION, **overrides})
    return response.json() | {"status_code": response.status_code}


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ─── Registration ─────────────────────────────────────────────────────────


def test_register_returns_a_usable_token(client: TestClient) -> None:
    response = client.post("/api/v1/auth/register", json=REGISTRATION)

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0

    me = client.get("/api/v1/auth/me", headers=auth_header(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == REGISTRATION["email"]


def test_register_never_returns_the_password_hash(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=REGISTRATION)
    token = client.post(
        "/api/v1/auth/login",
        json={"email": REGISTRATION["email"], "password": REGISTRATION["password"]},
    ).json()["access_token"]

    body = client.get("/api/v1/auth/me", headers=auth_header(token)).text

    assert "password" not in body.lower()
    assert "argon2" not in body.lower()


def test_password_is_stored_hashed_not_plaintext(client: TestClient, db_session: Session) -> None:
    client.post("/api/v1/auth/register", json=REGISTRATION)

    user = db_session.query(User).filter_by(email=REGISTRATION["email"]).one()

    assert user.password_hash != REGISTRATION["password"]
    assert user.password_hash.startswith("$argon2id$")


def test_registration_seeds_default_categories(client: TestClient, db_session: Session) -> None:
    """A user with no categories could not record a single transaction."""
    client.post("/api/v1/auth/register", json=REGISTRATION)

    user = db_session.query(User).filter_by(email=REGISTRATION["email"]).one()
    categories = db_session.query(Category).filter_by(user_id=user.id).all()

    assert len(categories) == len(DEFAULT_CATEGORIES)
    assert {category.name for category in categories} == {
        default.name for default in DEFAULT_CATEGORIES
    }


def test_duplicate_email_is_rejected(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=REGISTRATION)

    response = client.post("/api/v1/auth/register", json=REGISTRATION)

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_email_is_stored_lowercased(client: TestClient, db_session: Session) -> None:
    client.post("/api/v1/auth/register", json={**REGISTRATION, "email": "SAYED@Example.COM"})

    assert db_session.query(User).filter_by(email="sayed@example.com").count() == 1


def test_registration_with_differently_cased_email_is_a_duplicate(
    client: TestClient,
) -> None:
    client.post("/api/v1/auth/register", json=REGISTRATION)

    response = client.post(
        "/api/v1/auth/register", json={**REGISTRATION, "email": "SAYED@EXAMPLE.COM"}
    )

    assert response.status_code == 409


def test_invalid_email_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/auth/register", json={**REGISTRATION, "email": "nope"})

    assert response.status_code == 422


def test_short_password_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/auth/register", json={**REGISTRATION, "password": "short"})

    assert response.status_code == 422


def test_blank_name_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/auth/register", json={**REGISTRATION, "full_name": "   "})

    assert response.status_code == 422


# ─── Login ────────────────────────────────────────────────────────────────


def test_login_with_correct_credentials(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=REGISTRATION)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": REGISTRATION["email"], "password": REGISTRATION["password"]},
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_with_wrong_password_fails(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=REGISTRATION)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": REGISTRATION["email"], "password": "not-the-password"},
    )

    assert response.status_code == 401


def test_unknown_email_and_wrong_password_give_identical_responses(
    client: TestClient,
) -> None:
    """The response must not reveal which email addresses are registered."""
    client.post("/api/v1/auth/register", json=REGISTRATION)

    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"email": REGISTRATION["email"], "password": "not-the-password"},
    )
    unknown_email = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "not-the-password"},
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_login_is_case_insensitive_for_email(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=REGISTRATION)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "SAYED@EXAMPLE.COM", "password": REGISTRATION["password"]},
    )

    assert response.status_code == 200


def test_deactivated_account_cannot_log_in(client: TestClient, db_session: Session) -> None:
    client.post("/api/v1/auth/register", json=REGISTRATION)
    user = db_session.query(User).filter_by(email=REGISTRATION["email"]).one()
    user.is_active = False
    db_session.flush()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": REGISTRATION["email"], "password": REGISTRATION["password"]},
    )

    assert response.status_code == 401
    assert "deactivated" in response.json()["detail"]


# ─── Protected endpoints ──────────────────────────────────────────────────


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_me_rejects_a_forged_token(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me", headers=auth_header("not.a.token"))

    assert response.status_code == 401


def test_me_rejects_a_token_signed_with_another_key(client: TestClient) -> None:
    from app.core.config import Settings
    from app.core.security import create_access_token

    forged, _ = create_access_token(
        1, Settings(secret_key="an-attacker-key-long-enough-for-hmac-sha256")
    )

    response = client.get("/api/v1/auth/me", headers=auth_header(forged))

    assert response.status_code == 401


def test_token_for_a_deleted_user_is_rejected(client: TestClient, db_session: Session) -> None:
    token = client.post("/api/v1/auth/register", json=REGISTRATION).json()["access_token"]
    user = db_session.query(User).filter_by(email=REGISTRATION["email"]).one()
    db_session.delete(user)
    db_session.flush()

    response = client.get("/api/v1/auth/me", headers=auth_header(token))

    assert response.status_code == 401


def test_logout_requires_authentication(client: TestClient) -> None:
    assert client.post("/api/v1/auth/logout").status_code == 401


def test_logout_succeeds_when_authenticated(client: TestClient) -> None:
    token = client.post("/api/v1/auth/register", json=REGISTRATION).json()["access_token"]

    response = client.post("/api/v1/auth/logout", headers=auth_header(token))

    assert response.status_code == 204


# ─── Throttling ───────────────────────────────────────────────────────────
#
# Without a limit, a login form is an offline password guesser with a network
# in front of it. These use an app built with a small limit rather than the
# default ten, so a test does not have to pay for ten Argon2 verifications to
# reach the interesting case.


@pytest.fixture
def throttled(test_settings: Settings, db_session: Session) -> Iterator[TestClient]:
    """A client whose backend refuses after three failed sign-ins."""
    settings = test_settings.model_copy(
        update={
            "login_max_attempts": 3,
            "login_window_seconds": 300,
            "register_max_attempts": 2,
            "register_window_seconds": 3600,
        }
    )
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: db_session

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def attempt_login(client: TestClient, password: str = "wrong-password") -> object:
    return client.post(
        "/api/v1/auth/login",
        json={"email": REGISTRATION["email"], "password": password},
    )


def test_repeated_failed_sign_ins_are_eventually_refused(throttled: TestClient) -> None:
    throttled.post("/api/v1/auth/register", json=REGISTRATION)

    for _ in range(3):
        assert attempt_login(throttled).status_code == 401

    assert attempt_login(throttled).status_code == 429


def test_a_refusal_says_how_long_to_wait(throttled: TestClient) -> None:
    """A 429 without `Retry-After` tells a client to back off for an unknown
    length of time, which it can only answer by guessing."""
    throttled.post("/api/v1/auth/register", json=REGISTRATION)
    for _ in range(3):
        attempt_login(throttled)

    response = attempt_login(throttled)

    assert int(response.headers["retry-after"]) > 0
    assert "try again" in response.json()["detail"].lower()


def test_the_correct_password_is_refused_too_once_throttled(throttled: TestClient) -> None:
    """The point of a rate limit: it stops the guessing, not just the wrong
    guesses. Anything else would let an attacker verify a hit after the limit."""
    throttled.post("/api/v1/auth/register", json=REGISTRATION)
    for _ in range(3):
        attempt_login(throttled)

    response = attempt_login(throttled, password=REGISTRATION["password"])

    assert response.status_code == 429


def test_signing_in_successfully_clears_the_record(throttled: TestClient) -> None:
    """Two typos this morning must not still count against somebody this
    afternoon — a correct password is not a guess."""
    throttled.post("/api/v1/auth/register", json=REGISTRATION)
    attempt_login(throttled)
    attempt_login(throttled)

    assert attempt_login(throttled, password=REGISTRATION["password"]).status_code == 200

    # A full allowance again, rather than being one attempt from the limit.
    for _ in range(3):
        assert attempt_login(throttled).status_code == 401


def test_a_failed_sign_in_for_an_unknown_email_is_throttled_the_same_way(
    throttled: TestClient,
) -> None:
    """A throttle that only fired for real accounts would answer "does this
    email exist?" — the question ADR-018 exists to refuse."""
    for _ in range(3):
        assert attempt_login(throttled).status_code == 401

    refused = attempt_login(throttled)
    assert refused.status_code == 429


def test_the_refusal_never_says_how_many_attempts_are_left(throttled: TestClient) -> None:
    """That would hand an attacker a progress bar."""
    throttled.post("/api/v1/auth/register", json=REGISTRATION)

    bodies = [attempt_login(throttled).json()["detail"] for _ in range(3)]

    assert len(set(bodies)) == 1, "the message changed as the limit approached"


def test_creating_accounts_is_throttled_too(throttled: TestClient) -> None:
    """Each account costs a row in every table plus fifteen seeded categories."""
    assert register(throttled, email="one@example.com")["status_code"] == 201
    assert register(throttled, email="two@example.com")["status_code"] == 201

    assert register(throttled, email="three@example.com")["status_code"] == 429


def test_a_failed_registration_does_not_count(throttled: TestClient) -> None:
    """Successes are what is limited here, since the cost is the account."""
    register(throttled, email="one@example.com")
    for _ in range(4):
        # The same address twice: refused as a conflict, and not an account.
        assert register(throttled, email="one@example.com")["status_code"] == 409

    assert register(throttled, email="two@example.com")["status_code"] == 201


def test_throttling_does_not_leak_into_the_rest_of_the_api(throttled: TestClient) -> None:
    """Only the two unauthenticated endpoints are limited. A signed-in user
    reloading a screen must not be refused."""
    token = register(throttled, email="one@example.com")["access_token"]

    for _ in range(30):
        assert throttled.get("/api/v1/auth/me", headers=auth_header(token)).status_code == 200
