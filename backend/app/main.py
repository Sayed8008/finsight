"""FastAPI application entry point.

This module only wires the application together: configuration, logging,
middleware, and routers. It deliberately contains no business logic.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.error_handlers import register_error_handlers
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run startup and shutdown work.

    FastAPI calls this once when the process starts and once when it stops,
    which is where things like database connection pools will be opened and
    closed in later phases.
    """
    settings: Settings = app.state.settings
    logger.info("FinSight API starting (debug=%s)", settings.debug)
    yield
    logger.info("FinSight API shutting down")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application.

    Written as a factory rather than a module-level `app = FastAPI()` so that
    tests can construct an isolated instance with their own settings, instead
    of sharing one global object between test cases.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="FinSight API",
        description=(
            "Backend for FinSight, a personal finance and subscription "
            "intelligence desktop application."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings

    # The desktop client is not a browser and is unaffected by CORS. This is
    # kept narrow deliberately, so that a future web client has to be added
    # explicitly rather than by accident.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/health", tags=["system"], summary="Service health check")
    def health() -> dict[str, str]:
        """Report that the API process is running.

        Used by the desktop client at launch to tell "the backend is not
        running" apart from "the backend returned an error", so the user can
        be shown something more useful than a connection traceback.
        """
        return {"status": "ok", "service": "finsight-api", "version": "0.1.0"}

    return app


app = create_app()
