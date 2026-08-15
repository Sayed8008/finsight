#!/usr/bin/env bash
# Launch FinSight the way a desktop application starts: one action, no
# terminal, and nothing left running afterwards.
#
#     ./scripts/finsight.sh
#
# This is what the .desktop entry runs. It differs from `dev.sh` in the three
# ways that matter away from a terminal:
#
#   * it reports failures in a dialog rather than on stdout, because nobody
#     launching from an application menu is watching a console;
#   * it waits for the API to answer before showing the window, so the first
#     screen is never a "backend offline" one that fixes itself a second later;
#   * it stops the backend when the window closes, so quitting the application
#     actually quits it.

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
API_URL="http://127.0.0.1:8000"
backend_pid=""

# Tell the user, by whatever means exists. `zenity` is present on GNOME;
# `notify-send` is the fallback; stdout is the last resort for anyone who did
# run this from a terminal after all.
fail() {
    local message="$1"
    echo "FinSight: $message" >&2
    if command -v zenity >/dev/null 2>&1; then
        zenity --error --no-wrap --title="FinSight" --text="$message" 2>/dev/null
    elif command -v notify-send >/dev/null 2>&1; then
        notify-send --urgency=critical "FinSight" "$message"
    fi
    exit 1
}

cleanup() {
    if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
        kill "$backend_pid" 2>/dev/null || true
        wait "$backend_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

[[ -x "$VENV_PYTHON" ]] || fail \
    "The virtual environment is missing.\n\nExpected: $PROJECT_ROOT/.venv\n\nCreate it with:\n  python3 -m venv .venv\n  .venv/bin/pip install -r requirements.txt -r requirements-dev.txt"

[[ -f "$PROJECT_ROOT/.env" ]] || fail \
    "Configuration is missing.\n\nExpected: $PROJECT_ROOT/.env\n\nCopy .env.example to .env and set SECRET_KEY and the database URLs."

# If something already answers on the port, use it rather than starting a
# second copy — the port would be taken and the launch would fail for a
# reason that looks nothing like "it is already running".
if curl -fsS --max-time 2 "$API_URL/health" >/dev/null 2>&1; then
    echo "FinSight: an API is already running; using it."
else
    cd "$PROJECT_ROOT/backend" || fail "Cannot enter $PROJECT_ROOT/backend"
    "$VENV_PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 \
        >"${TMPDIR:-/tmp}/finsight-backend.log" 2>&1 &
    backend_pid=$!

    # Up to twenty seconds. MySQL may still be accepting connections when the
    # desktop session has only just started.
    ready=""
    for _ in $(seq 1 80); do
        if curl -fsS --max-time 1 "$API_URL/health" >/dev/null 2>&1; then
            ready="yes"
            break
        fi
        if ! kill -0 "$backend_pid" 2>/dev/null; then
            break   # it exited; the log will say why
        fi
        sleep 0.25
    done

    if [[ -z "$ready" ]]; then
        fail "The FinSight backend did not start.\n\nIts log is at ${TMPDIR:-/tmp}/finsight-backend.log\n\nThe usual cause is MySQL not running:\n  systemctl status mysql"
    fi
fi

cd "$PROJECT_ROOT/frontend" || fail "Cannot enter $PROJECT_ROOT/frontend"
"$VENV_PYTHON" -m client.main
