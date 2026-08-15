"""End-to-end tests for exporting transactions as CSV.

The format itself is covered as pure functions in
`tests/unit/test_transaction_csv.py`. What only a real database can answer is
here: that the filters are the same filters the list endpoint applies, that the
file is the whole matching set rather than a page of it, and that one account's
export cannot contain another's rows.
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.services.transaction_csv import BOM
from tests.conftest import Account

EXPORT = "/api/v1/csv/transactions"
TRANSACTIONS = "/api/v1/transactions"
CATEGORIES = "/api/v1/categories"


def category_id(client: TestClient, account: Account, name: str) -> int:
    body = client.get(CATEGORIES, headers=account.headers).json()
    return next(item["id"] for item in body if item["name"] == name)


def record(
    client: TestClient,
    account: Account,
    *,
    day: date = date(2026, 3, 4),
    amount: str = "499.00",
    description: str | None = "NETFLIX",
    category: str = "Subscriptions",
    kind: str = "expense",
    payment_method: str | None = None,
) -> None:
    payload = {
        "amount": amount,
        "transaction_type": kind,
        "category_id": category_id(client, account, category),
        "date": day.isoformat(),
        "description": description,
        "payment_method": payment_method,
    }
    response = client.post(TRANSACTIONS, json=payload, headers=account.headers)
    assert response.status_code == 201, response.text


def export(client: TestClient, account: Account, **params: object) -> str:
    response = client.get(EXPORT, headers=account.headers, params=params)
    assert response.status_code == 200, response.text
    return response.text


def rows(document: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(document.removeprefix(BOM))))


# ─── Shape ────────────────────────────────────────────────────────────────


def test_export_requires_authentication(client: TestClient) -> None:
    assert client.get(EXPORT).status_code == 401


def test_the_response_is_a_downloadable_csv_file(client: TestClient, account: Account) -> None:
    response = client.get(EXPORT, headers=account.headers)

    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert ".csv" in response.headers["content-disposition"]


def test_an_account_with_nothing_exports_a_header_and_no_rows(
    client: TestClient, account: Account
) -> None:
    """An empty file with no header would look like a failed export."""
    document = export(client, account)

    assert rows(document) == []
    assert "Date" in document


def test_a_transaction_becomes_a_row(client: TestClient, account: Account) -> None:
    record(client, account, amount="1234.50", description="NETFLIX", payment_method="bKash")

    row = rows(export(client, account))[0]

    assert row["Date"] == "2026-03-04"
    assert row["Amount"] == "1234.50"
    assert row["Type"] == "expense"
    assert row["Category"] == "Subscriptions"
    assert row["Description"] == "NETFLIX"
    assert row["Payment method"] == "bKash"


def test_amounts_carry_no_formatting(client: TestClient, account: Account) -> None:
    """A reader should not have to undo a thousands separator to get a number."""
    record(client, account, amount="12345.60")

    assert "12345.60" in export(client, account)


def test_rows_come_out_oldest_first(client: TestClient, account: Account) -> None:
    """A CSV is read as a statement, and a statement runs forwards."""
    for offset in (2, 0, 1):
        record(
            client,
            account,
            day=date(2026, 3, 4) + timedelta(days=offset),
            description=f"Day {offset}",
        )

    assert [row["Date"] for row in rows(export(client, account))] == [
        "2026-03-04",
        "2026-03-05",
        "2026-03-06",
    ]


# ─── Filters ──────────────────────────────────────────────────────────────


def test_the_export_honours_the_same_filters_the_list_does(
    client: TestClient, account: Account
) -> None:
    record(client, account, description="NETFLIX", category="Subscriptions")
    record(client, account, description="LUNCH", category="Food")

    document = export(client, account, category_id=category_id(client, account, "Food"))

    assert [row["Description"] for row in rows(document)] == ["LUNCH"]


def test_a_date_range_narrows_the_export(client: TestClient, account: Account) -> None:
    record(client, account, day=date(2026, 1, 5), description="January")
    record(client, account, day=date(2026, 6, 5), description="June")

    document = export(client, account, date_from="2026-05-01", date_to="2026-07-01")

    assert [row["Description"] for row in rows(document)] == ["June"]


def test_a_search_narrows_the_export(client: TestClient, account: Account) -> None:
    record(client, account, description="NETFLIX")
    record(client, account, description="SPOTIFY")

    assert len(rows(export(client, account, search="SPOT"))) == 1


def test_a_reversed_date_range_is_refused_rather_than_returning_nothing(
    client: TestClient, account: Account
) -> None:
    """The same rule the list applies — an empty file would look like no data."""
    response = client.get(
        EXPORT,
        headers=account.headers,
        params={"date_from": "2026-06-01", "date_to": "2026-01-01"},
    )

    assert response.status_code == 422


# ─── Not a page ───────────────────────────────────────────────────────────


def test_the_export_is_not_paginated(client: TestClient, account: Account) -> None:
    """A page of an export is a quietly truncated file that looks complete."""
    for index in range(30):
        record(client, account, day=date(2026, 3, 1) + timedelta(days=index))

    page = client.get(TRANSACTIONS, headers=account.headers).json()

    assert page["page_size"] == 25
    assert len(rows(export(client, account))) == 30


# ─── Scoping ──────────────────────────────────────────────────────────────


def test_one_account_cannot_export_another(
    client: TestClient, account: Account, other_account: Account
) -> None:
    record(client, other_account, description="SOMEONE ELSE")

    assert rows(export(client, account)) == []


# ─── Awkward content ──────────────────────────────────────────────────────


def test_a_description_a_spreadsheet_would_execute_is_defused(
    client: TestClient, account: Account
) -> None:
    """`=HYPERLINK(...)` is text here and a formula the moment Excel opens it."""
    record(client, account, description="=HYPERLINK('http://example.com')")

    row = rows(export(client, account))[0]

    assert row["Description"].startswith("'=")


def test_a_description_containing_the_delimiter_survives(
    client: TestClient, account: Account
) -> None:
    record(client, account, description="Lunch, coffee and a taxi")

    assert rows(export(client, account))[0]["Description"] == "Lunch, coffee and a taxi"


def test_a_transaction_with_no_description_exports_an_empty_cell(
    client: TestClient, account: Account
) -> None:
    record(client, account, description=None)

    row = rows(export(client, account))[0]

    assert row["Description"] == ""
    assert row["Payment method"] == ""
