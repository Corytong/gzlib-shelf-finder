#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "未找到 $PYTHON_BIN，请先安装 Python 3.10+" >&2
  exit 1
fi

if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
if [ -f requirements.txt ]; then
  python -m pip install -r requirements.txt
fi

echo ""
echo "环境已准备完成。"
echo "启动命令："
echo "  source .venv/bin/activate"
echo "  python server.py"
echo ""
echo "默认访问地址： http://127.0.0.1:${PORT:-8011}"
