#!/usr/bin/env python
"""Fill a demonstration account with a year of history.

    .venv/bin/python scripts/seed_demo.py
    .venv/bin/python scripts/seed_demo.py --email me@example.com --days 180

Requires the backend to be running (`./scripts/dev.sh backend`).

**It talks to the API, not to the database.** Writing rows directly would be
faster and would skip every rule the application enforces — the type/category
agreement, the budget overlap check, the derived billing dates. Seeding through
the API means the demo account is one an ordinary user could have produced, and
that a rule broken by the seed data fails here rather than on the day.

The history itself comes from `backend/tools/demo_data.py`, which is pure and
unit tested: there is a test that runs the real detector over it and asserts it
finds the three subscriptions and not the gym. This file is only the plumbing.

Existing data is never touched. If the account already exists, the script signs
in and adds to it — so running it twice doubles the history, which is exactly
what the duplicate detection in Phase 10 is for and a fine thing to demonstrate.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "frontend"))

from client.api.client import ApiClient, ApiError  # noqa: E402
from tools.demo_data import DemoHistory, build_history  # noqa: E402

DEFAULT_EMAIL = "demo@finsight.app"
DEFAULT_PASSWORD = "demo-account-password"
DEFAULT_NAME = "Md. Abu Sayed"


def sign_in_or_register(api: ApiClient, email: str, password: str, name: str) -> bool:
    """Return True if the account was created by this run.

    Registration is tried first and a 409 is treated as "it already exists",
    rather than checking first and then creating — between the check and the
    create, the answer could change, and the server is the only authority
    (ADR-019).
    """
    try:
        token = api.register(email, password, name)
        api.set_token(token.access_token)
        return True
    except ApiError as exc:
        if exc.status_code != 409:
            raise

    token = api.login(email, password)
    api.set_token(token.access_token)
    return False


def category_ids(api: ApiClient) -> dict[str, int]:
    """Every category by name, fetched once.

    Once, not once per row: a year of history is several hundred transactions
    and the same fifteen names — the same reason the import service builds a
    map instead of looking each one up (ADR-033).
    """
    return {category.name: category.id for category in api.categories(include_inactive=True)}


def seed(api: ApiClient, history: DemoHistory, *, quiet: bool = False) -> dict[str, int]:
    """Write the history through the API, reporting what was created."""
    categories = category_ids(api)

    missing = sorted(set(history.categories) - set(categories))
    if missing:
        raise SystemExit(
            f"This account has no {', '.join(missing)} category. "
            "The demo data expects the set a new account is seeded with."
        )

    counts = {"transactions": 0, "subscriptions": 0, "budgets": 0, "skipped": 0}

    for index, row in enumerate(history.transactions, start=1):
        try:
            api.create_transaction(**row.as_payload(categories[row.category]))
            counts["transactions"] += 1
        except ApiError as exc:
            counts["skipped"] += 1
            print(f"  skipped {row.date} {row.description}: {exc.message}", file=sys.stderr)

        if not quiet and index % 50 == 0:
            print(f"  {index}/{len(history.transactions)} transactions…")

    for subscription in history.subscriptions:
        try:
            api.create_subscription(**subscription.as_payload(categories[subscription.category]))
            counts["subscriptions"] += 1
        except ApiError as exc:
            counts["skipped"] += 1
            print(f"  skipped subscription {subscription.name}: {exc.message}", file=sys.stderr)

    for budget in history.budgets:
        try:
            api.create_budget(**budget.as_payload(categories[budget.category]))
            counts["budgets"] += 1
        except ApiError as exc:
            # A budget that already overlaps is the expected failure on a second
            # run (ADR-023), and not worth stopping for.
            counts["skipped"] += 1
            print(f"  skipped budget for {budget.category}: {exc.message}", file=sys.stderr)

    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument("--days", type=int, default=365, help="How much history to build.")
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Change this for different figures. The default is fixed so a demo can be rehearsed.",
    )
    parser.add_argument("--quiet", action="store_true")
    arguments = parser.parse_args()

    history = build_history(
        today=date.today(),
        days=arguments.days,
        **({"seed": arguments.seed} if arguments.seed is not None else {}),
    )

    with ApiClient() as api:
        try:
            api.health()
        except ApiError as exc:
            print(f"{exc.message}\nStart it with: ./scripts/dev.sh backend", file=sys.stderr)
            return 1

        try:
            created = sign_in_or_register(api, arguments.email, arguments.password, arguments.name)
        except ApiError as exc:
            print(f"Could not sign in as {arguments.email}: {exc.message}", file=sys.stderr)
            return 1

        print(f"{'Created' if created else 'Using existing'} account {arguments.email}")
        counts = seed(api, history, quiet=arguments.quiet)

    print(
        f"\nDone. {counts['transactions']} transactions, "
        f"{counts['subscriptions']} subscription, {counts['budgets']} budgets."
        + (f" {counts['skipped']} skipped." if counts["skipped"] else "")
    )
    print(f"\nSign in as {arguments.email} / {arguments.password}")
    print("Two of the three subscriptions in this history are untracked — try Find subscriptions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
