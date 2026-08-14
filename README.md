# FinSight

> Personal finance and subscription intelligence — a desktop application.

**Status:** in development (Phase 3 — authentication; register, sign in, sign out)

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
[`docs/DECISIONS.md`](docs/DECISIONS.md); current build status and what is
next are in [`docs/PROGRESS.md`](docs/PROGRESS.md).

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

Requires Python 3.11 or newer and MySQL 8.

**1. Install dependencies**

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

On Windows, use `.venv\Scripts\pip` instead.

**2. Configure**

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into SECRET_KEY
```

**3. Create the database**

```bash
./scripts/setup_database.sh
```

The script asks for a new password, creates the `finsight` and `finsight_test`
databases and a MySQL user restricted to them, then writes the connection URLs
into `.env`. The password is never stored in a tracked file.

**4. Apply database migrations**

```bash
cd backend && ../.venv/bin/python -m alembic upgrade head
```

Schema details and migration commands are in [`docs/DATABASE.md`](docs/DATABASE.md).

**5. Run**

```bash
./scripts/dev.sh              # Linux/macOS — starts backend and client
.\scripts\dev.ps1             # Windows PowerShell
```

Or run either half on its own with `./scripts/dev.sh backend` / `client`.

- API: <http://127.0.0.1:8000>
- Interactive API documentation: <http://127.0.0.1:8000/docs>

## Project layout

```
backend/
  app/
    api/v1/        route handlers — parse, delegate, return
    core/          configuration, logging, security
    db/            engine and session management
    models/        SQLAlchemy ORM models
    schemas/       Pydantic request/response models
    services/      business logic
    repositories/  database queries
    main.py        application factory
  tests/           unit/ and api/
frontend/
  client/
    api/           the only place the client makes HTTP calls
    core/          client configuration and session state
    views/         one view per section
    widgets/       reusable interface components
    resources/     stylesheet
    main.py        entry point
  tests/
docs/              architecture and decision records
scripts/           database setup and development launchers
```

## Testing

```bash
.venv/bin/python -m pytest              # everything
.venv/bin/python -m pytest backend      # backend only
.venv/bin/python -m pytest -m gui       # desktop client tests only
```

GUI tests use pytest-qt. On a machine with no display they automatically fall
back to Qt's offscreen renderer.

Linting and formatting use ruff:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format .
```

## License

To be decided.
