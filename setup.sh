#!/usr/bin/env bash
set -euo pipefail

# One-click setup for GZLib Shelf Finder
# - Installs Node dependencies
# - Creates a Python virtualenv and installs requirements

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if ! command -v npm >/dev/null 2>&1; then
  echo "[ERROR] npm not found. Install Node.js (LTS) first." >&2
  exit 1
fi

# Try python3 first, fallback to python
PYTHON=${PYTHON:-python3}
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  PYTHON=python
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "[ERROR] python/python3 not found." >&2
  exit 1
fi

# Node dependencies
if [ -f package-lock.json ]; then
  echo "==> npm ci"
  npm ci
else
  echo "==> npm install"
  npm install
fi

# Python env
if [ ! -d .venv ]; then
  echo "==> creating python venv"
  "$PYTHON" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> pip install -r requirements.txt"
pip install -r requirements.txt

echo "\nSetup complete.\n"
echo "Next steps:" 
echo "1) In one terminal run: source .venv/bin/activate && $PYTHON server.py" 
echo "2) In another terminal run: npm start" 
echo "Then open: http://127.0.0.1:8011"
