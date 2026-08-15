"""End-to-end tests for importing transactions from CSV.

Parsing is covered as pure functions in `tests/unit/test_transaction_csv.py`.
What is here is everything that needs a real database, and most of it is about
what the import *refuses* to do:

  * a preview writes nothing, whatever it finds;
  * an import applies only a file that was previewed, with the options it was
    previewed under;
  * a failure partway through leaves no rows and no categories behind;
  * an unknown category, an unreadable row and a duplicate each stop the import
    rather than being quietly resolved.

The last of those is the point of the whole phase. A file that half imports is
worse than one that does not import at all, because nobody can tell which half
landed.
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.services.import_service import ImportService
from tests.conftest import Account, QueryCounter

PREVIEW = "/api/v1/csv/preview"
IMPORT = "/api/v1/csv/import"
EXPORT = "/api/v1/csv/transactions"
TRANSACTIONS = "/api/v1/transactions"
CATEGORIES = "/api/v1/categories"

HEADER = "Date,Amount,Type,Category,Description,Payment method"


# ─── Helpers ──────────────────────────────────────────────────────────────


def csv_text(*rows: str, header: str = HEADER) -> str:
    return "\n".join((header, *rows)) + "\n"


def upload(text: str) -> dict[str, tuple[str, bytes, str]]:
    return {"file": ("statement.csv", text.encode("utf-8"), "text/csv")}


def preview(client: TestClient, account: Account, text: str, **options: object) -> dict:
    response = client.post(PREVIEW, files=upload(text), params=options, headers=account.headers)
    assert response.status_code == 200, response.text
    return response.json()


def do_import(client: TestClient, account: Account, text: str, **options: object):
    """Preview, then import with the fingerprint the preview handed back."""
    plan = preview(client, account, text, **options)
    return client.post(
        IMPORT,
        files=upload(text),
        params={**options, "digest": plan["digest"]},
        headers=account.headers,
    )


def import_ok(client: TestClient, account: Account, text: str, **options: object) -> dict:
    response = do_import(client, account, text, **options)
    assert response.status_code == 200, response.text
    return response.json()


def recorded(client: TestClient, account: Account) -> list[dict]:
    response = client.get(TRANSACTIONS, headers=account.headers, params={"page_size": 200})
    assert response.status_code == 200, response.text
    return response.json()["items"]


def category_names(client: TestClient, account: Account) -> list[str]:
    body = client.get(
        CATEGORIES, headers=account.headers, params={"include_inactive": True}
    ).json()
    return [item["name"] for item in body]


def category_id(client: TestClient, account: Account, name: str) -> int:
    body = client.get(
        CATEGORIES, headers=account.headers, params={"include_inactive": True}
    ).json()
    return next(item["id"] for item in body if item["name"] == name)


ONE_GOOD_ROW = csv_text("2026-03-04,499.00,expense,Subscriptions,NETFLIX,bKash")


# ─── The preview writes nothing ───────────────────────────────────────────


def test_preview_requires_authentication(client: TestClient) -> None:
    assert client.post(PREVIEW, files=upload(ONE_GOOD_ROW)).status_code == 401


def test_import_requires_authentication(client: TestClient) -> None:
    assert client.post(IMPORT, files=upload(ONE_GOOD_ROW)).status_code == 401


def test_a_preview_creates_nothing(client: TestClient, account: Account) -> None:
    """The constraint the whole design rests on."""
    plan = preview(client, account, ONE_GOOD_ROW)

    assert plan["would_import"] == 1
    assert recorded(client, account) == []


def test_previewing_twice_gives_the_same_answer(client: TestClient, account: Account) -> None:
    """It holds no state, so it cannot drift between runs."""
    first = preview(client, account, ONE_GOOD_ROW)
    second = preview(client, account, ONE_GOOD_ROW)

    assert first == second


def test_a_preview_reports_what_it_recognised(client: TestClient, account: Account) -> None:
    plan = preview(client, account, ONE_GOOD_ROW)

    assert set(plan["columns"]) >= {"date", "amount", "category", "description"}
    assert plan["encoding"] == "utf-8-sig"


def test_the_preview_shows_the_rows_as_it_read_them(client: TestClient, account: Account) -> None:
    """Reading `2026-03-04` back out of `04/03/2026` is how somebody catches
    the wrong date order in two seconds rather than in six months."""
    plan = preview(
        client,
        account,
        csv_text("04/03/2026,499.00,expense,Subscriptions,NETFLIX,"),
        date_order="day_first",
    )

    assert plan["sample"][0]["date"] == "2026-03-04"
    assert plan["sample"][0]["amount"] == "499.00"


def test_the_sample_is_a_sample_not_the_file_again(client: TestClient, account: Account) -> None:
    rows = [f"2026-03-{day:02d},10.00,expense,Food,Lunch {day}" for day in range(1, 29)]
    plan = preview(client, account, csv_text(*rows))

    assert plan["total_rows"] == 28
    assert plan["would_import"] == 28
    assert len(plan["sample"]) == 10


# ─── A file that cannot be read at all ────────────────────────────────────


def test_a_file_with_no_date_column_is_refused_outright(
    client: TestClient, account: Account
) -> None:
    response = client.post(
        PREVIEW,
        files=upload("Amount,Category\n5.00,Food\n"),
        headers=account.headers,
    )

    assert response.status_code == 422
    assert "date" in response.json()["detail"]


def test_an_empty_file_is_refused(client: TestClient, account: Account) -> None:
    response = client.post(PREVIEW, files=upload(""), headers=account.headers)

    assert response.status_code == 422


def test_a_file_with_no_category_column_needs_somewhere_to_put_the_rows(
    client: TestClient, account: Account
) -> None:
    """`transactions.category_id` is NOT NULL and there is no "uncategorised"
    row to hide behind (ADR-006)."""
    bank_statement = csv_text(
        "2026-03-04,-499.00,NETFLIX", header="Date,Amount,Description"
    )

    refused = client.post(PREVIEW, files=upload(bank_statement), headers=account.headers)
    assert refused.status_code == 422

    plan = preview(
        client,
        account,
        bank_statement,
        default_category_id=category_id(client, account, "Other"),
    )
    assert plan["would_import"] == 1


def test_the_fallback_category_must_suit_the_direction(
    client: TestClient, account: Account
) -> None:
    """Filing income under an expense category corrupts every total that
    trusts the pair."""
    plan = preview(
        client,
        account,
        csv_text(
            "2026-03-04,45000.00,income,MONTHLY SALARY",
            header="Date,Amount,Type,Description",
        ),
        default_category_id=category_id(client, account, "Food"),
    )

    assert plan["would_import"] == 0
    assert plan["problems"][0]["column"] == "category"


# ─── Importing what was previewed, and only that ──────────────────────────


def test_a_previewed_file_imports(client: TestClient, account: Account) -> None:
    result = import_ok(client, account, ONE_GOOD_ROW)

    assert result["imported"] == 1
    row = recorded(client, account)[0]
    assert row["amount"] == "499.00"
    assert row["date"] == "2026-03-04"
    assert row["description"] == "NETFLIX"
    assert row["payment_method"] == "bKash"
    assert row["category"]["name"] == "Subscriptions"


def test_an_import_without_a_fingerprint_is_rejected(
    client: TestClient, account: Account
) -> None:
    """There is no way to import a file that was never previewed."""
    response = client.post(IMPORT, files=upload(ONE_GOOD_ROW), headers=account.headers)

    assert response.status_code == 422
    assert recorded(client, account) == []


def test_a_fingerprint_from_a_different_file_is_rejected(
    client: TestClient, account: Account
) -> None:
    plan = preview(client, account, ONE_GOOD_ROW)
    other = csv_text("2026-03-04,99999.00,expense,Subscriptions,SOMETHING ELSE,")

    response = client.post(
        IMPORT,
        files=upload(other),
        params={"digest": plan["digest"]},
        headers=account.headers,
    )

    assert response.status_code == 409
    assert recorded(client, account) == []


def test_changing_an_option_after_previewing_is_rejected(
    client: TestClient, account: Account
) -> None:
    """Previewing as day-first and importing as month-first would write a set
    of rows nobody ever looked at."""
    text = csv_text("03/04/2026,499.00,expense,Subscriptions,NETFLIX,")
    plan = preview(client, account, text, date_order="day_first")

    response = client.post(
        IMPORT,
        files=upload(text),
        params={"digest": plan["digest"], "date_order": "month_first"},
        headers=account.headers,
    )

    assert response.status_code == 409
    assert recorded(client, account) == []


def test_the_date_order_decides_which_day_lands(client: TestClient, account: Account) -> None:
    import_ok(
        client,
        account,
        csv_text("03/04/2026,499.00,expense,Subscriptions,NETFLIX,"),
        date_order="day_first",
    )

    assert recorded(client, account)[0]["date"] == "2026-04-03"


# ─── All or nothing ───────────────────────────────────────────────────────


def test_a_failure_partway_through_leaves_nothing_behind(
    client: TestClient, account: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the phase. Rows *and* the categories created for them
    go back, because "half imported" includes the half nobody asked about."""
    real_insert = ImportService._insert_rows

    def insert_then_fail(self, user_id, plan, created):  # type: ignore[no-untyped-def]
        real_insert(self, user_id, plan, created)
        raise RuntimeError("the connection went away")

    monkeypatch.setattr(ImportService, "_insert_rows", insert_then_fail)

    text = csv_text(
        "2026-03-04,10.00,expense,Fitness,GYM,",
        "2026-03-05,20.00,expense,Fitness,GYM SHOP,",
    )
    plan = preview(client, account, text, unknown_categories="create")

    with pytest.raises(RuntimeError):
        client.post(
            IMPORT,
            files=upload(text),
            params={"digest": plan["digest"], "unknown_categories": "create"},
            headers=account.headers,
        )

    assert recorded(client, account) == []
    assert "Fitness" not in category_names(client, account)


def test_one_unreadable_row_stops_the_whole_file(client: TestClient, account: Account) -> None:
    text = csv_text(
        "2026-03-04,10.00,expense,Food,Lunch,",
        "not-a-date,20.00,expense,Food,Dinner,",
        "2026-03-06,30.00,expense,Food,Coffee,",
    )

    plan = preview(client, account, text)
    assert plan["blockers"]
    assert plan["would_import"] == 0

    response = do_import(client, account, text)

    assert response.status_code == 422
    assert recorded(client, account) == []


def test_the_preview_says_which_row_and_why(client: TestClient, account: Account) -> None:
    """A blocked import that does not say what to fix is a wall."""
    plan = preview(
        client,
        account,
        csv_text(
            "2026-03-04,10.00,expense,Food,Lunch,",
            "not-a-date,20.00,expense,Food,Dinner,",
        ),
    )

    problem = plan["problems"][0]
    assert problem["line_number"] == 3
    assert problem["column"] == "date"
    assert "not-a-date" in problem["value"]


def test_the_rest_can_be_imported_once_that_has_been_seen(
    client: TestClient, account: Account
) -> None:
    """The permissive option exists, but only after the preview has named
    exactly which rows it would leave out."""
    text = csv_text(
        "2026-03-04,10.00,expense,Food,Lunch,",
        "not-a-date,20.00,expense,Food,Dinner,",
    )

    result = import_ok(client, account, text, skip_invalid=True)

    assert result["imported"] == 1
    assert result["skipped_invalid"] == 1
    assert [row["description"] for row in recorded(client, account)] == ["Lunch"]


# ─── Categories ───────────────────────────────────────────────────────────


def test_an_unknown_category_stops_the_import_by_default(
    client: TestClient, account: Account
) -> None:
    text = csv_text("2026-03-04,10.00,expense,Skydiving,JUMP,")

    plan = preview(client, account, text)

    assert plan["would_import"] == 0
    assert any("Skydiving" in blocker for blocker in plan["blockers"])
    assert do_import(client, account, text).status_code == 422


def test_the_preview_names_every_category_and_its_fate(
    client: TestClient, account: Account
) -> None:
    plan = preview(
        client,
        account,
        csv_text(
            "2026-03-04,10.00,expense,Food,Lunch,",
            "2026-03-05,20.00,expense,Skydiving,Jump,",
            "2026-03-06,30.00,expense,Skydiving,Jump again,",
        ),
    )

    fates = {item["name"]: (item["action"], item["rows"]) for item in plan["categories"]}
    assert fates["Food"] == ("matched", 1)
    assert fates["Skydiving"] == ("unknown", 2)


def test_unknown_categories_can_be_created_as_part_of_the_import(
    client: TestClient, account: Account
) -> None:
    result = import_ok(
        client,
        account,
        csv_text("2026-03-04,10.00,expense,Skydiving,JUMP,"),
        unknown_categories="create",
    )

    assert result["created_categories"] == ["Skydiving"]
    assert "Skydiving" in category_names(client, account)
    assert recorded(client, account)[0]["category"]["name"] == "Skydiving"


def test_a_created_category_is_made_once_however_many_rows_use_it(
    client: TestClient, account: Account
) -> None:
    import_ok(
        client,
        account,
        csv_text(
            "2026-03-04,10.00,expense,Skydiving,One,",
            "2026-03-05,20.00,expense,Skydiving,Two,",
            "2026-03-06,30.00,expense,skydiving,Three,",
        ),
        unknown_categories="create",
    )

    assert category_names(client, account).count("Skydiving") == 1
    assert len(recorded(client, account)) == 3


def test_a_category_name_matches_whatever_its_case(
    client: TestClient, account: Account
) -> None:
    import_ok(client, account, csv_text("2026-03-04,10.00,expense,fOOd,Lunch,"))

    assert recorded(client, account)[0]["category"]["name"] == "Food"


def test_a_deactivated_category_stops_the_import(client: TestClient, account: Account) -> None:
    """New records may not attach to a retired category (ADR-020). Quietly
    dropping every row that names one would be worse than refusing."""
    food = category_id(client, account, "Food")
    client.patch(f"{CATEGORIES}/{food}", json={"is_active": False}, headers=account.headers)

    plan = preview(client, account, csv_text("2026-03-04,10.00,expense,Food,Lunch,"))

    assert plan["would_import"] == 0
    assert any("deactivated" in blocker for blocker in plan["blockers"])
    assert plan["categories"][0]["action"] == "inactive"


def test_a_category_of_the_wrong_direction_is_named_as_such(
    client: TestClient, account: Account
) -> None:
    """"Salary" exists — as income. An expense cannot go in it, and saying
    "unknown category" would send the user looking for a name that is there."""
    plan = preview(client, account, csv_text("2026-03-04,10.00,expense,Salary,Odd,"))

    assert plan["categories"][0]["action"] == "wrong_type"
    assert any("other direction" in blocker for blocker in plan["blockers"])


def test_an_income_row_is_filed_under_an_income_category(
    client: TestClient, account: Account
) -> None:
    import_ok(client, account, csv_text("2026-03-04,45000.00,income,Salary,MONTHLY,"))

    row = recorded(client, account)[0]
    assert row["transaction_type"] == "income"
    assert row["category"]["category_type"] == "income"


def test_another_accounts_categories_are_not_reachable(
    client: TestClient, account: Account, other_account: Account
) -> None:
    """A category id from elsewhere is not a way into another account."""
    theirs = category_id(client, other_account, "Food")

    response = client.post(
        PREVIEW,
        files=upload(
            csv_text("2026-03-04,10.00,expense,NETFLIX", header="Date,Amount,Type,Description")
        ),
        params={"default_category_id": theirs},
        headers=account.headers,
    )

    assert response.status_code == 422


# ─── Duplicates ───────────────────────────────────────────────────────────


def test_importing_the_same_file_twice_does_not_double_the_history(
    client: TestClient, account: Account
) -> None:
    """The most likely way to use this feature wrongly."""
    import_ok(client, account, ONE_GOOD_ROW)

    plan = preview(client, account, ONE_GOOD_ROW)
    assert plan["duplicate_rows"] == 1
    assert plan["would_import"] == 0
    assert plan["duplicates"][0]["source"] == "history"

    assert do_import(client, account, ONE_GOOD_ROW).status_code == 422
    assert len(recorded(client, account)) == 1


def test_a_row_repeated_inside_the_file_is_reported_as_such(
    client: TestClient, account: Account
) -> None:
    plan = preview(
        client,
        account,
        csv_text(
            "2026-03-04,499.00,expense,Subscriptions,NETFLIX,",
            "2026-03-04,499.00,expense,Subscriptions,NETFLIX,",
        ),
    )

    assert plan["duplicate_rows"] == 1
    assert plan["duplicates"][0]["source"] == "file"
    assert plan["would_import"] == 1


def test_duplicates_can_be_imported_when_that_is_what_is_meant(
    client: TestClient, account: Account
) -> None:
    """Two identical charges on one day is a real thing that happens."""
    import_ok(client, account, ONE_GOOD_ROW)

    result = import_ok(client, account, ONE_GOOD_ROW, skip_duplicates=False)

    assert result["imported"] == 1
    assert len(recorded(client, account)) == 2


def test_a_row_with_no_description_is_never_called_a_duplicate(
    client: TestClient, account: Account
) -> None:
    """Two undescribed 250.00 expenses on one day are indistinguishable from
    the same charge twice, and a row wrongly skipped is data silently lost."""
    text = csv_text(
        "2026-03-04,250.00,expense,Food,,",
        "2026-03-04,250.00,expense,Food,,",
    )

    result = import_ok(client, account, text)

    assert result["imported"] == 2
    assert result["skipped_duplicates"] == 0


def test_a_similar_but_different_row_is_not_a_duplicate(
    client: TestClient, account: Account
) -> None:
    import_ok(client, account, ONE_GOOD_ROW)

    result = import_ok(
        client, account, csv_text("2026-03-04,500.00,expense,Subscriptions,NETFLIX,")
    )

    assert result["imported"] == 1


def test_another_accounts_rows_are_not_duplicates_of_these(
    client: TestClient, account: Account, other_account: Account
) -> None:
    import_ok(client, other_account, ONE_GOOD_ROW)

    result = import_ok(client, account, ONE_GOOD_ROW)

    assert result["imported"] == 1


# ─── Cost ─────────────────────────────────────────────────────────────────


def statements_to_import(
    client: TestClient, account: Account, counter: QueryCounter, rows: int
) -> int:
    text = csv_text(
        *(
            f"2026-01-01,{index + 1}.00,expense,Food,Lunch {index},"
            for index in range(rows)
        )
    )
    plan = preview(client, account, text)
    counter.reset()
    response = client.post(
        IMPORT,
        files=upload(text),
        params={"digest": plan["digest"]},
        headers=account.headers,
    )
    assert response.status_code == 200, response.text
    return len(counter.statements)


def test_the_cost_of_an_import_barely_moves_with_its_size(
    client: TestClient, account: Account, other_account: Account, query_counter: QueryCounter
) -> None:
    """Five thousand rows must not become five thousand inserts, nor five
    thousand category lookups. Counting is the only thing that catches it —
    an N+1 import is functionally perfect and unusable."""
    small = statements_to_import(client, account, query_counter, 10)
    large = statements_to_import(client, other_account, query_counter, 200)

    assert large - small <= 2


def test_two_hundred_rows_arrive_intact(client: TestClient, account: Account) -> None:
    """Batched inserts are worth nothing if they lose a row on a boundary."""
    text = csv_text(
        *(
            f"{date(2026, 1, 1) + timedelta(days=index)},{index + 1}.00,expense,Food,Row {index},"
            for index in range(200)
        )
    )

    result = import_ok(client, account, text)

    assert result["imported"] == 200
    assert result["first_date"] == "2026-01-01"
    assert result["last_date"] == "2026-07-19"


# ─── Round trip ───────────────────────────────────────────────────────────


def test_an_export_can_be_imported_into_an_empty_account(
    client: TestClient, account: Account, other_account: Account
) -> None:
    """The strongest single check on both halves: whatever one account exports,
    another can read back without a single option being changed."""
    import_ok(
        client,
        account,
        csv_text(
            "2026-03-04,1234.50,expense,Food,Lunch out,Cash",
            "2026-03-05,45000.00,income,Salary,Monthly salary,Bank transfer",
            "2026-03-06,499.00,expense,Subscriptions,=NETFLIX,bKash",
        ),
    )
    exported = client.get(EXPORT, headers=account.headers).text

    result = import_ok(client, other_account, exported)

    assert result["imported"] == 3
    mine = client.get(EXPORT, headers=account.headers).text
    theirs = client.get(EXPORT, headers=other_account.headers).text
    assert mine == theirs


# ─── Awkward files ────────────────────────────────────────────────────────


def test_a_windows_encoded_file_is_read_and_says_so(
    client: TestClient, account: Account
) -> None:
    """Refusing a file over one accented character helps nobody, but which
    encoding read it is reported so mojibake has a visible cause."""
    text = csv_text("2026-03-04,10.00,expense,Food,Café Müller,")
    response = client.post(
        PREVIEW,
        files={"file": ("statement.csv", text.encode("cp1252"), "text/csv")},
        headers=account.headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["encoding"] == "cp1252"
    assert body["sample"][0]["description"] == "Café Müller"


def test_a_semicolon_file_is_read_as_one(client: TestClient, account: Account) -> None:
    text = "Date;Amount;Type;Category;Description\n2026-03-04;1.234,56;expense;Food;Lunch\n"

    result = import_ok(client, account, text)

    assert result["imported"] == 1
    assert recorded(client, account)[0]["amount"] == "1234.56"


def test_ambiguous_dates_are_flagged_without_stopping_the_import(
    client: TestClient, account: Account
) -> None:
    """A warning, not an error: the user is told a choice was made for them."""
    plan = preview(
        client,
        account,
        csv_text(
            "03/04/2026,10.00,expense,Food,One,",
            "20/06/2026,20.00,expense,Food,Two,",
        ),
        date_order="day_first",
    )

    assert plan["ambiguous_dates"] == 1
    assert plan["blockers"] == []
    assert plan["would_import"] == 2


def test_a_file_of_nothing_but_duplicates_says_so_rather_than_succeeding_emptily(
    client: TestClient, account: Account
) -> None:
    import_ok(client, account, ONE_GOOD_ROW)

    plan = preview(client, account, ONE_GOOD_ROW)

    assert any("already recorded" in blocker for blocker in plan["blockers"])


def test_an_imported_history_is_what_detection_reads(
    client: TestClient, account: Account
) -> None:
    """Import is the natural feeder for Phase 9.5: a year of history is exactly
    what makes detection worth running."""
    rows = [
        f"{date(2026, 1, 5) + timedelta(days=30 * index)},499.00,expense,"
        f"Subscriptions,NETFLIX.COM {index},"
        for index in range(5)
    ]

    import_ok(client, account, csv_text(*rows))

    found = client.post(
        "/api/v1/subscriptions/detect",
        headers=account.headers,
        params={"as_of": "2026-06-15"},
    ).json()

    assert [candidate["name"] for candidate in found["candidates"]] == ["Netflix"]


def test_the_exported_file_names_the_columns_the_importer_looks_for(
    client: TestClient, account: Account
) -> None:
    """Stated as a test rather than as a comment, because the two lists living
    in different modules is exactly how they come apart."""
    header = client.get(EXPORT, headers=account.headers).text.splitlines()[0]
    fields = next(csv.reader(io.StringIO(header)))

    plan = preview(client, account, csv_text(header=",".join(fields)) + "\n")

    assert set(plan["columns"]) == {
        "date",
        "amount",
        "type",
        "category",
        "description",
        "payment_method",
    }
