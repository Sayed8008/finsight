"""Desktop client configuration.

Deliberately separate from the backend's settings module: the client is a
different process with different concerns, and it must never import backend
code. It only needs to know where the API lives.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"


@dataclass(frozen=True)
class ClientConfig:
    """Runtime configuration for the desktop application."""

    api_base_url: str = DEFAULT_API_BASE_URL
    request_timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> ClientConfig:
        return cls(
            api_base_url=os.environ.get("FINSIGHT_API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/"),
        )

    @property
    def api_v1_url(self) -> str:
        return f"{self.api_base_url}/api/v1"
