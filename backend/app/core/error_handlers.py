"""Translation of exceptions into HTTP responses.

Registered once on the application. Two things follow from doing it centrally:

  * services can raise domain errors without importing anything from FastAPI;
  * every error response has the same shape, `{"detail": "..."}`, which is
    also what FastAPI's own validation errors use, so the desktop client
    needs exactly one code path for failures.

An unexpected exception is logged in full and answered with a generic message.
A stack trace or database error text in a response would disclose internal
detail to whoever provoked it.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    """Attach exception handlers to the application."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        # Expected failures — wrong password, duplicate email, missing record.
        # Logged at info because they are normal application flow, not faults.
        logger.info(
            "%s on %s %s: %s",
            type(exc).__name__,
            request.method,
            request.url.path,
            exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
            # Almost always empty. A 429 carries `Retry-After`, without which
            # the status tells a client to back off for an unknown length of
            # time and it can only guess.
            headers=exc.headers or None,
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        # Database errors often quote the failing SQL, including column values.
        # The detail goes to the log; the client gets none of it.
        logger.exception("Database error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "A database error occurred. Please try again."},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Something went wrong. Please try again."},
        )
