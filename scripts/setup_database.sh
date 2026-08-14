#!/usr/bin/env bash
# FinSight — one-time database setup.
#
#     ./scripts/setup_database.sh
#
# Prompts for a password, creates the `finsight` and `finsight_test` databases
# and a MySQL user restricted to them, then writes the connection URLs into
# .env (which is git-ignored).
#
# The password is never written to any file that git tracks. That is why this
# is a script that asks, rather than a .sql file with the password typed in.
#
# Requires an administrative MySQL login, so it uses sudo.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
DB_USER="finsight"
DB_NAME="finsight"
DB_TEST_NAME="finsight_test"

if ! command -v mysql >/dev/null 2>&1; then
    echo "Error: the mysql client is not installed." >&2
    echo "On Ubuntu:  sudo apt install mysql-server" >&2
    exit 1
fi

echo "FinSight database setup"
echo "-----------------------"
echo "This creates two databases ($DB_NAME, $DB_TEST_NAME) and a MySQL user"
echo "named '$DB_USER' that can access only those two."
echo
echo "Choose a NEW password for that user. It is not your Ubuntu password and"
echo "not your GitHub password — it is only used by this application."
echo

# -s hides the input; -r stops backslashes being interpreted.
read -rsp "Password for MySQL user '$DB_USER': " DB_PASSWORD
echo
read -rsp "Confirm password: " DB_PASSWORD_CONFIRM
echo
echo

if [[ -z "$DB_PASSWORD" ]]; then
    echo "Error: password cannot be empty." >&2
    exit 1
fi

if [[ "$DB_PASSWORD" != "$DB_PASSWORD_CONFIRM" ]]; then
    echo "Error: passwords do not match." >&2
    exit 1
fi

# Escape single quotes so a password containing one cannot break (or alter)
# the SQL statement below.
SQL_SAFE_PASSWORD="${DB_PASSWORD//\'/\'\'}"

echo "Creating databases and user (you may be asked for your sudo password)..."

# utf8mb4 is real UTF-8, including Bangla text and the currency sign.
# MySQL 8.4 removed mysql_native_password, so caching_sha2_password is used;
# PyMySQL needs the `cryptography` package to authenticate with it.
sudo mysql <<SQL
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\`
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE DATABASE IF NOT EXISTS \`${DB_TEST_NAME}\`
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost'
    IDENTIFIED WITH caching_sha2_password BY '${SQL_SAFE_PASSWORD}';

ALTER USER '${DB_USER}'@'localhost'
    IDENTIFIED WITH caching_sha2_password BY '${SQL_SAFE_PASSWORD}';

-- Least privilege: rights on these two schemas only, nothing global.
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.*      TO '${DB_USER}'@'localhost';
GRANT ALL PRIVILEGES ON \`${DB_TEST_NAME}\`.* TO '${DB_USER}'@'localhost';

FLUSH PRIVILEGES;
SQL

echo "Databases created."
echo

echo "Verifying that the application user can connect..."
for database in "$DB_NAME" "$DB_TEST_NAME"; do
    if MYSQL_PWD="$DB_PASSWORD" mysql -u "$DB_USER" -h 127.0.0.1 "$database" \
        -e "SELECT 1;" >/dev/null 2>&1; then
        echo "  ok: $database"
    else
        echo "  FAILED: could not connect to $database as '$DB_USER'" >&2
        exit 1
    fi
done
echo

# Write the connection URLs into .env. The password is percent-encoded so that
# characters like @ : / # do not corrupt the URL.
echo "Updating $ENV_FILE ..."
DB_PASSWORD="$DB_PASSWORD" \
DB_USER="$DB_USER" DB_NAME="$DB_NAME" DB_TEST_NAME="$DB_TEST_NAME" \
ENV_FILE="$ENV_FILE" PROJECT_ROOT="$PROJECT_ROOT" \
"${PROJECT_ROOT}/.venv/bin/python" - <<'PY'
import os
import pathlib
import re
import urllib.parse

env_path = pathlib.Path(os.environ["ENV_FILE"])
example_path = pathlib.Path(os.environ["PROJECT_ROOT"]) / ".env.example"

if not env_path.exists():
    env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    print("  created .env from .env.example")

password = urllib.parse.quote(os.environ["DB_PASSWORD"], safe="")
user = os.environ["DB_USER"]

urls = {
    "DATABASE_URL": f"mysql+pymysql://{user}:{password}@localhost:3306/{os.environ['DB_NAME']}",
    "TEST_DATABASE_URL": (
        f"mysql+pymysql://{user}:{password}@localhost:3306/{os.environ['DB_TEST_NAME']}"
    ),
}

content = env_path.read_text(encoding="utf-8")
for key, value in urls.items():
    pattern = rf"^{key}=.*$"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, f"{key}={value}", content, flags=re.MULTILINE)
    else:
        content += f"\n{key}={value}\n"
    print(f"  set {key}")

env_path.write_text(content, encoding="utf-8")
PY

echo
echo "Done. .env now holds the connection details and is git-ignored."
echo "Next: database models and the first migration (Phase 2)."
