# Database schema

MySQL 8.4, `utf8mb4` throughout. Managed entirely through Alembic migrations —
tables are never altered by hand.

## Overview

```
                        ┌───────────┐
                        │   users   │
                        └─────┬─────┘
                              │ 1
             ┌────────────────┼────────────────┬─────────────────┐
             │ n              │ n              │ n               │ n
       ┌─────▼──────┐  ┌──────▼───────┐  ┌─────▼─────┐  ┌────────▼───────┐
       │ categories │  │ transactions │  │  budgets  │  │ subscriptions  │
       └─────┬──────┘  └──────▲───────┘  └─────▲─────┘  └────────▲───────┘
             │ 1              │ n              │ n               │ n
             └────────────────┴────────────────┴─────────────────┘
                        (categories classify all three)
```

Every table carries a `user_id`. That single invariant is what lets the
"users may only access their own data" rule be enforced in one shared
dependency instead of endpoint by endpoint.

## Tables

### `users`

| Column | Type | Notes |
|---|---|---|
| `id` | INT PK | |
| `email` | VARCHAR(255) | unique, indexed |
| `password_hash` | VARCHAR(255) | Argon2id; never a plaintext password |
| `full_name` | VARCHAR(120) | |
| `currency_code` | CHAR(3) | ISO 4217, default `BDT` |
| `role` | ENUM | `user` / `admin` |
| `is_active` | BOOL | deactivate rather than delete |
| `created_at`, `updated_at` | DATETIME | UTC |

### `categories`

Per-user, seeded when an account is created (ADR-006).

| Column | Type | Notes |
|---|---|---|
| `id` | INT PK | |
| `user_id` | FK → `users` | `ON DELETE CASCADE`, indexed |
| `name` | VARCHAR(80) | |
| `category_type` | ENUM | `income` / `expense` |
| `color`, `icon` | VARCHAR | for charts and category chips |
| `is_active` | BOOL | deactivated, never deleted |

**Unique:** `(user_id, category_type, name)` — "Other" may exist once as income
and once as expense, but not twice within one type.

### `transactions`

| Column | Type | Notes |
|---|---|---|
| `id` | INT PK | |
| `user_id` | FK → `users` | `ON DELETE CASCADE` |
| `amount` | DECIMAL(14,2) | always positive |
| `transaction_type` | ENUM | `income` / `expense` — carries the direction |
| `category_id` | FK → `categories` | `ON DELETE RESTRICT` |
| `date` | DATE | a calendar date, not a timestamp |
| `description` | VARCHAR(255) | |
| `payment_method` | VARCHAR(50) | a string for now, not a table |

**Check:** `amount > 0`.
**Indexes:** `(user_id, date)`, `(user_id, category_id)`,
`(user_id, transaction_type)`.

`RESTRICT` on the category is deliberate: deleting a category must not silently
delete the transactions filed under it.

### `budgets`

| Column | Type | Notes |
|---|---|---|
| `id` | INT PK | |
| `user_id` | FK → `users` | |
| `category_id` | FK → `categories` | |
| `amount` | DECIMAL(14,2) | the limit |
| `period_start`, `period_end` | DATE | inclusive both ends |

**Checks:** `amount > 0`, `period_end >= period_start`.
**Unique:** `(user_id, category_id, period_start, period_end)`.

Spent, remaining, percentage used and status are **computed on read**, never
stored — a stored total goes stale the moment a transaction changes.

An explicit date range rather than a month/year pair means weekly or quarterly
budgets later are a data change, not a schema migration.

### `subscriptions`

| Column | Type | Notes |
|---|---|---|
| `id` | INT PK | |
| `user_id` | FK → `users` | |
| `category_id` | FK → `categories`, nullable | `ON DELETE SET NULL` |
| `name` | VARCHAR(120) | |
| `amount` | DECIMAL(14,2) | per billing cycle |
| `billing_cycle` | ENUM | `weekly`/`monthly`/`quarterly`/`yearly` |
| `status` | ENUM | `active`/`paused`/`cancelled` |
| `start_date`, `next_billing_date` | DATE | |
| `end_date` | DATE, nullable | |
| `payment_method` | VARCHAR(50) | |
| `notes` | TEXT | |

**Checks:** `amount > 0`, `end_date IS NULL OR end_date >= start_date`.
**Index:** `(user_id, status, next_billing_date)` — serves upcoming renewals.

`category_id` is nullable because a subscription detected from transaction
history may not have been categorised yet.

Monthly and yearly equivalent costs are derived at read time, not stored.

## Conventions

**Money** — `DECIMAL(14,2)` in MySQL, `Decimal` in Python, string in JSON.
Never `float` (ADR-003).

**Timestamps** — all UTC, stored as naive `DATETIME` because MySQL's DATETIME
carries no timezone. Defaults are applied in Python so they do not depend on
the database server's clock. Conversion to local time is the interface's job.

**Constraint names** — fixed by a naming convention in `app/db/base.py`.
Without it, the database invents names and Alembic later generates migrations
that try to drop constraints by names that do not match.

## Working with migrations

All commands run from `backend/`.

```bash
# After changing a model — generate a migration
../.venv/bin/python -m alembic revision --autogenerate -m "add x to y"

# Review the generated file, then apply it
../.venv/bin/python -m alembic upgrade head

# Undo the most recent migration
../.venv/bin/python -m alembic downgrade -1

# Show current revision / history
../.venv/bin/python -m alembic current
../.venv/bin/python -m alembic history
```

Autogenerate is a starting point, not an oracle — always read the generated
file before applying it.

The connection URL comes from `.env` via `alembic/env.py`, never from
`alembic.ini`, so the database password stays out of version control.

`backend/tests/db/test_migrations.py` fails the build if the models and the
migrations disagree, which catches the common mistake of changing a model and
forgetting to generate the migration.
