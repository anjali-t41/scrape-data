#!/usr/bin/env bash
# push.sh — collect local Claude Code data and push to the central store
# Usage:
#   ./push.sh                          # uses POSTGRES_URL env var
#   ./push.sh --since 7d               # override period
#   ./push.sh --central <url> --since 7d
#   ./push.sh --dry-run                # preview without writing

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Python check ──────────────────────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c "import sys; print(sys.version_info >= (3,11))" 2>/dev/null)
        if [ "$version" = "True" ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3.11+ not found. Install from https://python.org" >&2
    exit 1
fi

echo "[push] Platform : $(uname -s) ($(uname -m))"
echo "[push] Python   : $($PYTHON --version)"

# ── Virtual environment ───────────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "[push] Creating virtual environment..."
    "$PYTHON" -m venv .venv
fi

VENV_PYTHON=".venv/bin/python"
VENV_PIP=".venv/bin/pip"

echo "[push] Installing dependencies..."
"$VENV_PIP" install -q -r requirements.txt

# ── Run push ──────────────────────────────────────────────────────────────────
echo "[push] Starting push..."
echo ""
"$VENV_PYTHON" push.py "$@"
