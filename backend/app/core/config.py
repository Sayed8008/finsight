"""Application configuration.

Settings are read from environment variables, falling back to the project's
`.env` file. Nothing in the codebase should read `os.environ` directly — every
value goes through the `Settings` object defined here, so that:

  * each value has a declared type and is validated once, at startup;
  * a missing or malformed value fails immediately with a clear message,
    rather than surfacing as a confusing error deep inside a request;
  * there is exactly one place to look to see what the app can be configured
    with.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py -> core -> app -> backend -> <project root>
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Value shipped in .env.example. If it survives into a real environment, the
# developer forgot to generate a key.
PLACEHOLDER_SECRET = "CHANGE_ME_GENERATE_A_RANDOM_VALUE"

# HS256 signs with HMAC-SHA256; RFC 7518 §3.2 requires a key of at least the
# hash size. Enforced outside debug mode.
MIN_SECRET_KEY_BYTES = 32


class Settings(BaseSettings):
    """Typed application settings, loaded once at startup."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── Database ─────────────────────────────────────────────────────────
    database_url: str = Field(
        default="mysql+pymysql://finsight:finsight@localhost:3306/finsight",
        description="SQLAlchemy connection URL for the application database.",
    )
    test_database_url: str = Field(
        default="mysql+pymysql://finsight:finsight@localhost:3306/finsight_test",
        description="Connection URL used by the test suite. Tests destroy data.",
    )

    # ─── Security ─────────────────────────────────────────────────────────
    secret_key: str = Field(
        default=PLACEHOLDER_SECRET,
        description="Key used to sign access tokens. Must be random and secret.",
    )
    access_token_expire_minutes: int = 60
    jwt_algorithm: str = "HS256"

    # ─── API server ───────────────────────────────────────────────────────
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = Field(
        default="http://localhost:8000",
        description="Comma-separated list of origins permitted by CORS.",
    )

    # ─── Application ──────────────────────────────────────────────────────
    debug: bool = True
    log_level: str = "INFO"
    default_currency: str = "BDT"

    # Note: the desktop client's own settings live in
    # frontend/client/core/config.py. The backend has no need of them, and
    # `extra="ignore"` above means sharing one .env file is harmless.

    # ─── Derived values ───────────────────────────────────────────────────
    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list, since env vars can only hold strings."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def api_v1_prefix(self) -> str:
        return "/api/v1"

    # ─── Validation ───────────────────────────────────────────────────────
    @model_validator(mode="after")
    def _reject_placeholder_secret_outside_debug(self) -> Settings:
        """Allow the placeholder key in development only.

        Running with a known, published signing key in production would let
        anyone forge a valid access token for any user.

        This is a model validator rather than a field validator because it
        depends on two fields, and Pydantic validates fields in declaration
        order — a field validator on `secret_key` would run before `debug`
        had been populated.
        """
        if self.debug:
            return self

        if self.secret_key == PLACEHOLDER_SECRET:
            raise ValueError(
                "SECRET_KEY is still the placeholder from .env.example. "
                'Generate one with: python -c "import secrets; '
                'print(secrets.token_urlsafe(48))"'
            )

        # RFC 7518 §3.2: an HMAC key should be at least as long as the hash
        # output — 32 bytes for SHA-256. A shorter key weakens the signature
        # that every access token depends on.
        if len(self.secret_key.encode()) < MIN_SECRET_KEY_BYTES:
            raise ValueError(
                f"SECRET_KEY must be at least {MIN_SECRET_KEY_BYTES} bytes "
                f"(got {len(self.secret_key.encode())}). "
                'Generate one with: python -c "import secrets; '
                'print(secrets.token_urlsafe(48))"'
            )

        return self

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        level = value.upper()
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in valid:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(valid)}, got {value!r}")
        return level


@lru_cache
def get_settings() -> Settings:
    """Return the application settings.

    Cached so the `.env` file is read once per process rather than on every
    access, and so every caller sees the same object.
    """
    return Settings()
