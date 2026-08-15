"""Tests for the sliding-window rate limiter.

The clock is a parameter, so every one of these runs in a millisecond and still
means something. A limiter tested with `sleep` would either be slow or would
test a window so short that none of the boundaries below could be reached.
"""

from __future__ import annotations

import pytest

from app.core.rate_limit import Decision, SlidingWindowLimiter

KEY = "203.0.113.7"
OTHER = "198.51.100.4"


def limiter(limit: int = 3, window: float = 60.0, capacity: int = 1000) -> SlidingWindowLimiter:
    return SlidingWindowLimiter(limit=limit, window_seconds=window, capacity=capacity)


def exhaust(bucket: SlidingWindowLimiter, key: str = KEY, at: float = 0.0, times: int = 3) -> None:
    for index in range(times):
        bucket.record(key, at + index)


# ─── Allowing ─────────────────────────────────────────────────────────────


def test_a_key_with_no_history_is_allowed() -> None:
    assert limiter().check(KEY, 0.0) == Decision(allowed=True, remaining=3, retry_after_seconds=0)


def test_checking_does_not_count_as_an_attempt() -> None:
    """The two happen at different moments: a request is refused before the
    password is checked, and counted only once it is known to have failed."""
    bucket = limiter()

    for _ in range(10):
        bucket.check(KEY, 0.0)

    assert bucket.check(KEY, 0.0).allowed is True


def test_attempts_below_the_limit_are_allowed() -> None:
    bucket = limiter(limit=3)

    assert bucket.record(KEY, 0.0).allowed is True
    assert bucket.record(KEY, 1.0).allowed is True


def test_the_remaining_count_falls_with_each_attempt() -> None:
    bucket = limiter(limit=3)

    assert bucket.record(KEY, 0.0).remaining == 2
    assert bucket.record(KEY, 1.0).remaining == 1


# ─── Refusing ─────────────────────────────────────────────────────────────


def test_recording_says_where_the_key_now_stands_not_whether_it_was_allowed() -> None:
    """`record` answers "what would `check` say next", because gating happens
    before the work rather than after it."""
    bucket = limiter(limit=3)

    assert bucket.record(KEY, 0.0).allowed is True
    assert bucket.record(KEY, 1.0).allowed is True
    # The third fills the window, so the *next* attempt is the refused one.
    assert bucket.record(KEY, 2.0).allowed is False
    assert bucket.check(KEY, 2.0).allowed is False


def test_a_refused_key_stays_refused_within_the_window() -> None:
    bucket = limiter(limit=3, window=60.0)
    exhaust(bucket)

    assert bucket.check(KEY, 30.0).allowed is False


def test_a_refusal_says_how_long_to_wait() -> None:
    """A 429 without that is an instruction to back off for an unknown time,
    which a client can only answer by guessing."""
    bucket = limiter(limit=3, window=60.0)
    exhaust(bucket, at=0.0)

    decision = bucket.check(KEY, 10.0)

    # The window frees up when the oldest of the three falls out of it.
    assert decision.retry_after_seconds == 51


def test_the_wait_is_never_zero() -> None:
    """`Retry-After: 0` invites an immediate retry, which is the opposite of
    the point."""
    bucket = limiter(limit=1, window=1.0)
    bucket.record(KEY, 0.0)

    assert bucket.check(KEY, 0.999).retry_after_seconds >= 1


# ─── The window sliding ───────────────────────────────────────────────────


def test_an_attempt_older_than_the_window_no_longer_counts() -> None:
    bucket = limiter(limit=3, window=60.0)
    exhaust(bucket, at=0.0)

    assert bucket.check(KEY, 61.0).allowed is True


def test_the_window_slides_rather_than_resetting() -> None:
    """A fixed window resets on a boundary, so an attacker who waits for it can
    spend a full allowance either side and get twice the intended rate. There
    is no boundary here to stand on."""
    bucket = limiter(limit=3, window=60.0)
    bucket.record(KEY, 0.0)
    bucket.record(KEY, 30.0)
    bucket.record(KEY, 59.0)

    # A fixed 60-second window would reset wholesale at t=60 and hand back all
    # three. Only the first has aged out, so there is room for exactly one.
    assert bucket.check(KEY, 61.0) == Decision(
        allowed=True, remaining=1, retry_after_seconds=0
    )
    bucket.record(KEY, 61.0)
    assert bucket.check(KEY, 62.0).allowed is False


def test_attempts_expire_one_at_a_time() -> None:
    bucket = limiter(limit=2, window=10.0)
    bucket.record(KEY, 0.0)
    bucket.record(KEY, 5.0)

    assert bucket.check(KEY, 11.0).remaining == 1
    assert bucket.check(KEY, 16.0).remaining == 2


# ─── Keys are separate ────────────────────────────────────────────────────


def test_one_key_being_refused_does_not_refuse_another() -> None:
    """The reason attempts are counted per address and not per email: counting
    per email would let anybody lock out an account they do not own."""
    bucket = limiter(limit=3)
    exhaust(bucket, key=KEY)

    assert bucket.check(KEY, 3.0).allowed is False
    assert bucket.check(OTHER, 3.0).allowed is True


def test_clearing_a_key_forgets_its_history() -> None:
    """What a successful sign-in does: a correct password is not a guess."""
    bucket = limiter(limit=3)
    exhaust(bucket)

    bucket.clear(KEY)

    assert bucket.check(KEY, 3.0).allowed is True


def test_clearing_an_unknown_key_is_harmless() -> None:
    limiter().clear("never seen")


# ─── Bounded memory ───────────────────────────────────────────────────────


def test_the_store_does_not_grow_without_limit() -> None:
    """A dictionary keyed by client address is one an attacker chooses the keys
    of. Left alone it is a memory leak with a hostile author."""
    bucket = limiter(limit=5, capacity=10)

    for index in range(500):
        bucket.record(f"10.0.0.{index}", float(index))

    assert len(bucket._attempts) <= 10


def test_eviction_drops_the_least_recently_seen() -> None:
    """Safe in the direction that matters: an old, quiet attacker gets their
    allowance back, while whoever is active right now stays limited."""
    bucket = limiter(limit=1, capacity=2)
    bucket.record("first", 0.0)
    bucket.record("second", 1.0)
    bucket.record("third", 2.0)

    assert bucket.check("first", 3.0).allowed is True
    assert bucket.check("third", 3.0).allowed is False


def test_a_key_that_goes_quiet_frees_its_memory() -> None:
    bucket = limiter(limit=3, window=10.0)
    exhaust(bucket, at=0.0)

    bucket.check(KEY, 100.0)

    assert KEY not in bucket._attempts


# ─── Refusing to be built wrongly ─────────────────────────────────────────


@pytest.mark.parametrize("limit", [0, -1])
def test_a_limit_below_one_is_refused(limit: int) -> None:
    """It would refuse every attempt, including the first, which is a locked
    door rather than a rate limit."""
    with pytest.raises(ValueError, match="refuse every attempt"):
        SlidingWindowLimiter(limit=limit, window_seconds=60)


@pytest.mark.parametrize("window", [0, -5])
def test_a_window_with_no_length_is_refused(window: float) -> None:
    with pytest.raises(ValueError, match="must have a length"):
        SlidingWindowLimiter(limit=5, window_seconds=window)
