# FinSight

> Personal finance and subscription intelligence — a desktop application.

**Status:** in development (Phase 0 — project foundation)

FinSight helps a single user understand where their money goes: spending by
category, budget health, savings trends, and — its distinguishing feature —
automatic detection of recurring subscriptions hidden inside ordinary
transaction history.

FinSight does **not** connect to bank accounts or payment providers. All data is
entered manually or imported from CSV.

---

## Technology stack

| Layer | Technology |
|---|---|
| Desktop client | PySide6 (Qt 6), QtCharts |
| API | FastAPI |
| Business logic | Python service layer |
| Data access | SQLAlchemy 2.0 (synchronous) |
| Migrations | Alembic |
| Database | MySQL 8.4 (PyMySQL driver) |
| Validation | Pydantic v2 / Pydantic Settings |
| Testing | pytest, httpx, pytest-qt |

Runs on Linux and Windows.

## Architecture

```
PySide6 widgets
      │
      ▼
  API client            ← the only place the GUI performs HTTP
      │
      ▼  HTTP / REST
FastAPI routers         ← parse, delegate, return
      │
      ▼
  Services              ← business logic, Decimal arithmetic
      │
      ▼
 Repositories           ← all SQLAlchemy query construction
      │
      ▼
    MySQL
```

The GUI never touches the database. Business logic never appears in widgets or
in route handlers.

Design decisions and their rationale are recorded in
[`docs/DECISIONS.md`](docs/DECISIONS.md).

## Features

Planned for the first release:

- User accounts with Argon2id password hashing and JWT-authenticated API access
- Manual transaction entry, CSV import (with validation preview) and CSV export
- Categories, budgets with utilisation tracking, and recurring subscriptions
- Dashboard with financial overview and charts
- Analytics over selectable time ranges
- A deterministic, explainable rule-based insights engine
- Automatic detection of recurring subscriptions from transaction history

## Getting started

> Setup instructions are added in Phase 1, once there is an application to run.

## Project layout

```
backend/    FastAPI application, services, repositories, models, migrations
frontend/   PySide6 desktop client
docs/       Architecture and decision records
scripts/    Development and setup helpers
```

## Testing

> Added in Phase 1.

## License

To be decided.
