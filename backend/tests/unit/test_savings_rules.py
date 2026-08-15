"""Tests for the savings badges and observations.

Pure arithmetic and pure rules, so these build months and call functions —
no database, no clock, no HTTP.

The property worth defending here is that a badge cannot be bought with a
salary. Somebody earning three times as much saves three times as much
without changing a single habit, so every test that could reward income
checks the rate or the comparison against the same person's own history
instead.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.savings_rules import (
    CONSISTENT_MONTHS,
    STREAK_MONTHS,
    STRONG_SAVER_RATE,
    BadgeCode,
    SavingsMonth,
    award,
    best_month,
    observations,
    positive_streak,
)


def month(year: int, number: int, income: str, expense: str) -> SavingsMonth:
    return SavingsMonth(
        year=year, month=number, income=Decimal(income), expense=Decimal(expense)
    )


def codes(months: list[SavingsMonth]) -> set[str]:
    return {badge.code for badge in award(months)}


# ─── The calculation ──────────────────────────────────────────────────────


def test_a_normal_month_keeps_what_is_left() -> None:
    assert month(2026, 1, "50000.00", "30000.00").net == Decimal("20000.00")


def test_savings_are_that_month_only_and_never_accumulate() -> None:
    """The trap this feature exists to avoid. Two identical months each saved
    20,000 — the second did not save 40,000."""
    january = month(2026, 1, "50000.00", "30000.00")
    february = month(2026, 2, "50000.00", "30000.00")

    assert january.net == Decimal("20000.00")
    assert february.net == Decimal("20000.00")


def test_spending_more_than_you_earned_is_a_negative_result() -> None:
    """A deficit, not a small positive saving and not an absolute value."""
    assert month(2026, 1, "40000.00", "45000.00").net == Decimal("-5000.00")


def test_the_rate_is_the_share_of_income_kept() -> None:
    assert month(2026, 1, "50000.00", "30000.00").rate == Decimal("40.00")


def test_a_month_with_no_income_has_a_zero_rate_rather_than_an_error() -> None:
    """Dividing by nothing would raise; inventing 0% or 100% would both be
    claims about a month that earned nothing. Zero is decided once, in
    `percentage_of`."""
    assert month(2026, 1, "0.00", "5000.00").rate == Decimal("0.00")
    assert month(2026, 1, "0.00", "0.00").rate == Decimal("0.00")


def test_a_deficit_rate_is_negative() -> None:
    assert month(2026, 1, "40000.00", "45000.00").rate == Decimal("-12.50")


def test_the_rate_is_rounded_to_two_places_half_up() -> None:
    """1,000 of 3,000 is 33.333…, and money rounds half away from zero."""
    assert month(2026, 1, "3000.00", "2000.00").rate == Decimal("33.33")
    assert month(2026, 1, "3000.00", "1000.00").rate == Decimal("66.67")


def test_a_month_that_broke_even_is_not_positive() -> None:
    """Zero saved is a real result, and it is not a saving."""
    assert month(2026, 1, "50000.00", "50000.00").net == Decimal("0.00")
    assert month(2026, 1, "50000.00", "50000.00").is_positive is False


# ─── Streaks ──────────────────────────────────────────────────────────────


def test_a_streak_counts_back_from_the_latest_month() -> None:
    """A good run three years ago must not earn a badge today."""
    months = [
        month(2026, 1, "50000.00", "10000.00"),  # positive
        month(2026, 2, "50000.00", "10000.00"),  # positive
        month(2026, 3, "50000.00", "60000.00"),  # broke the run
        month(2026, 4, "50000.00", "10000.00"),  # positive
    ]

    assert positive_streak(months) == 1


def test_a_streak_of_nothing_is_zero() -> None:
    assert positive_streak([]) == 0
    assert positive_streak([month(2026, 1, "10.00", "20.00")]) == 0


def test_a_break_even_month_ends_a_streak() -> None:
    months = [
        month(2026, 1, "50000.00", "10000.00"),
        month(2026, 2, "50000.00", "50000.00"),
    ]

    assert positive_streak(months) == 0


# ─── Personal best ────────────────────────────────────────────────────────


def test_the_best_month_is_the_one_that_saved_most() -> None:
    months = [
        month(2026, 1, "50000.00", "45000.00"),
        month(2026, 2, "50000.00", "20000.00"),
        month(2026, 3, "50000.00", "40000.00"),
    ]

    assert best_month(months) == months[1]


def test_there_is_no_best_month_when_none_saved_anything() -> None:
    """A record of losses is not a personal best."""
    months = [month(2026, 1, "10.00", "20.00"), month(2026, 2, "10.00", "30.00")]

    assert best_month(months) is None


def test_a_tie_belongs_to_the_month_that_set_it_first() -> None:
    """The record was reached when it was first reached, not when matched."""
    months = [
        month(2026, 1, "50000.00", "30000.00"),
        month(2026, 2, "50000.00", "30000.00"),
    ]

    assert best_month(months) == months[0]


def test_one_month_is_not_a_personal_best() -> None:
    """A record needs something to be a record *of*."""
    assert BadgeCode.PERSONAL_BEST not in codes([month(2026, 1, "50000.00", "10000.00")])


def test_the_best_month_earns_the_badge_only_when_it_is_the_latest() -> None:
    earlier_best = [
        month(2026, 1, "50000.00", "10000.00"),
        month(2026, 2, "50000.00", "45000.00"),
    ]
    latest_best = [
        month(2026, 1, "50000.00", "45000.00"),
        month(2026, 2, "50000.00", "10000.00"),
    ]

    assert BadgeCode.PERSONAL_BEST not in codes(earlier_best)
    assert BadgeCode.PERSONAL_BEST in codes(latest_best)


# ─── Badges ───────────────────────────────────────────────────────────────


def test_no_history_earns_nothing() -> None:
    assert award([]) == []


def test_improving_needs_a_month_to_improve_on() -> None:
    assert BadgeCode.IMPROVING not in codes([month(2026, 1, "50000.00", "10000.00")])


def test_improving_is_awarded_for_beating_last_month() -> None:
    months = [
        month(2026, 1, "50000.00", "45000.00"),
        month(2026, 2, "50000.00", "40000.00"),
    ]

    assert BadgeCode.IMPROVING in codes(months)


def test_improving_is_not_awarded_for_saving_less() -> None:
    months = [
        month(2026, 1, "50000.00", "40000.00"),
        month(2026, 2, "50000.00", "45000.00"),
    ]

    assert BadgeCode.IMPROVING not in codes(months)


def test_improving_counts_a_smaller_deficit_as_improvement() -> None:
    """Losing 1,000 after losing 5,000 is progress, and saying otherwise
    would only ever discourage the person who most needs the encouragement."""
    months = [
        month(2026, 1, "10000.00", "15000.00"),  # -5,000
        month(2026, 2, "10000.00", "11000.00"),  # -1,000
    ]

    assert BadgeCode.IMPROVING in codes(months)


def test_a_streak_is_awarded_at_the_documented_threshold() -> None:
    below = [month(2026, i + 1, "50000.00", "10000.00") for i in range(STREAK_MONTHS - 1)]
    at = [month(2026, i + 1, "50000.00", "10000.00") for i in range(STREAK_MONTHS)]

    assert BadgeCode.STREAK not in codes(below)
    assert BadgeCode.STREAK in codes(at)


def test_a_long_streak_becomes_consistency_rather_than_both() -> None:
    """Two badges saying the same thing is nagging, so the longer one wins."""
    months = [
        month(2025 + i // 12, i % 12 + 1, "50000.00", "10000.00")
        for i in range(CONSISTENT_MONTHS)
    ]
    earned = codes(months)

    assert BadgeCode.CONSISTENT in earned
    assert BadgeCode.STREAK not in earned


def test_strong_saver_is_awarded_on_rate_not_on_amount() -> None:
    """The badge that could most easily reward a salary. A modest income
    keeping a quarter of it earns it; a large income keeping a twentieth of
    it — far more money — does not."""
    modest = [month(2026, 1, "20000.00", "15000.00")]  # 5,000 saved, 25%
    large = [month(2026, 1, "500000.00", "480000.00")]  # 20,000 saved, 4%

    assert BadgeCode.STRONG_SAVER in codes(modest)
    assert BadgeCode.STRONG_SAVER not in codes(large)


def test_strong_saver_sits_exactly_on_its_threshold() -> None:
    at = [month(2026, 1, "100000.00", str(100000 - int(STRONG_SAVER_RATE) * 1000) + ".00")]
    below = [month(2026, 1, "100000.00", "81000.00")]  # 19%

    assert BadgeCode.STRONG_SAVER in codes(at)
    assert BadgeCode.STRONG_SAVER not in codes(below)


def test_a_deficit_earns_no_badges_at_all() -> None:
    months = [
        month(2026, 1, "50000.00", "45000.00"),
        month(2026, 2, "40000.00", "60000.00"),
    ]

    assert codes(months) == set()


def test_every_badge_names_the_figure_that_earned_it() -> None:
    """A badge that cannot say why it appeared is decoration."""
    months = [
        month(2025, 12, "50000.00", "45000.00"),
        month(2026, 1, "50000.00", "40000.00"),
        month(2026, 2, "50000.00", "20000.00"),
    ]

    for badge in award(months):
        assert badge.detail
        assert any(character.isdigit() for character in badge.detail), badge


# ─── Observations ─────────────────────────────────────────────────────────


def test_no_history_says_nothing() -> None:
    assert observations([]) == []


def test_the_best_month_is_named_with_its_figure() -> None:
    months = [
        month(2026, 2, "50000.00", "45000.00"),
        month(2026, 3, "50000.00", "36000.00"),
    ]

    assert "March 2026 was your best savings month — you saved 14,000.00." in observations(
        months
    )


def test_saving_more_than_last_month_is_stated_as_a_difference() -> None:
    months = [
        month(2026, 1, "50000.00", "40000.00"),  # 10,000
        month(2026, 2, "50000.00", "38000.00"),  # 12,000
    ]

    assert "You saved 2,000.00 more than last month." in observations(months)


def test_saving_less_is_stated_as_a_positive_amount_less() -> None:
    """"You saved -2,000.00 more" would be arithmetic nobody reads."""
    months = [
        month(2026, 1, "50000.00", "38000.00"),
        month(2026, 2, "50000.00", "40000.00"),
    ]

    assert "You saved 2,000.00 less than last month." in observations(months)


def test_a_rate_that_moved_is_reported_from_and_to() -> None:
    months = [
        month(2026, 1, "50000.00", "41000.00"),  # 18%
        month(2026, 2, "50000.00", "38000.00"),  # 24%
    ]

    assert "Your savings rate improved from 18% to 24%." in observations(months)


def test_a_streak_is_stated_once_it_is_worth_stating() -> None:
    months = [month(2026, i + 1, "50000.00", "10000.00") for i in range(3)]

    assert "You maintained positive savings for 3 consecutive months." in observations(months)


def test_a_deficit_month_is_said_plainly() -> None:
    months = [
        month(2026, 1, "50000.00", "40000.00"),
        month(2026, 2, "40000.00", "45000.00"),
    ]

    assert "February 2026 spent 5,000.00 more than it earned." in observations(months)


@pytest.mark.parametrize("count", [1, 2, 3, 12, 24])
def test_observations_never_raise_whatever_the_history(count: int) -> None:
    months = [
        month(2025 + i // 12, i % 12 + 1, "50000.00", "40000.00") for i in range(count)
    ]

    assert isinstance(observations(months), list)
