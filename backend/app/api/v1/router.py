"""Version 1 API router.

Each feature area contributes a router, and they are collected here. Adding a
module to the API is then a single line in one file, rather than an edit to
the application factory.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, budgets, categories, transactions

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(categories.router)
api_router.include_router(transactions.router)
api_router.include_router(budgets.router)
