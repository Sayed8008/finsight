"""Tests for application configuration.

Configuration is easy to get wrong in ways that only surface in production,
so the validation rules are tested directly.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import PLACEHOLDER_SECRET, Settings


def test_cors_origins_are_split_into_a_list() -> None:
    settings = Settings(cors_origins="http://a.test, http://b.test ,")

    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]


def test_log_level_is_normalised_to_upper_case() -> None:
    assert Settings(log_level="debug").log_level == "DEBUG"


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level="verbose")


def test_placeholder_secret_is_allowed_in_debug() -> None:
    """Developers should not need to generate a key just to run the app."""
    settings = Settings(debug=True, secret_key=PLACEHOLDER_SECRET)

    assert settings.secret_key == PLACEHOLDER_SECRET


def test_placeholder_secret_is_rejected_outside_debug() -> None:
    """A published signing key would let anyone forge a token for any user."""
    with pytest.raises(ValidationError, match="placeholder"):
        Settings(debug=False, secret_key=PLACEHOLDER_SECRET)
