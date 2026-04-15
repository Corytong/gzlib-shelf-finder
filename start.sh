#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

if [ ! -d ".venv" ]; then
  echo "请先运行 ./setup.sh" >&2
  exit 1
fi

source .venv/bin/activate
exec python server.py
