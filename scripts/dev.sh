#!/usr/bin/env bash
# Start the FinSight backend and desktop client together (Linux / macOS).
#
#     ./scripts/dev.sh            start both
#     ./scripts/dev.sh backend    start only the API
#     ./scripts/dev.sh client     start only the desktop client
#
# The backend is stopped automatically when this script exits.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
MODE="${1:-both}"

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "Virtual environment not found at $PROJECT_ROOT/.venv" >&2
    echo "Create it with:" >&2
    echo "    python3 -m venv .venv" >&2
    echo "    .venv/bin/pip install -r requirements.txt -r requirements-dev.txt" >&2
    exit 1
fi

backend_pid=""

cleanup() {
    if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
        echo
        echo "Stopping backend (pid $backend_pid)..."
        kill "$backend_pid" 2>/dev/null || true
        wait "$backend_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

start_backend() {
    echo "Starting API on http://127.0.0.1:8000  (docs at /docs)"
    cd "$PROJECT_ROOT/backend"
    "$VENV_PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload &
    backend_pid=$!
    cd "$PROJECT_ROOT"
}

wait_for_backend() {
    echo -n "Waiting for the API to become ready"
    for _ in $(seq 1 40); do
        if "$VENV_PYTHON" -c "
import sys, httpx2
try:
    httpx2.get('http://127.0.0.1:8000/health', timeout=1.0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
            echo " ready."
            return 0
        fi
        echo -n "."
        sleep 0.25
    done
    echo " timed out (starting the client anyway)."
    return 1
}

start_client() {
    echo "Starting desktop client"
    cd "$PROJECT_ROOT/frontend"
    "$VENV_PYTHON" -m client.main
}

case "$MODE" in
    backend)
        start_backend
        wait "$backend_pid"
        ;;
    client)
        start_client
        ;;
    both)
        start_backend
        wait_for_backend || true
        start_client
        ;;
    *)
        echo "Usage: $0 [both|backend|client]" >&2
        exit 1
        ;;
esac
