#!/usr/bin/env bash
# 一键启动故事链协议服务（需本机已安装 Python 3.9+）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
VENV="$ROOT/.venv-api"
PORT="${PORT:-8000}"

pick_python() {
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

if ! PY="$(pick_python)"; then
  echo "未找到 Python。请先安装 Python 3.9+ 后再双击本脚本。"
  echo "macOS: https://www.python.org/downloads/"
  read -r -p "按回车退出..." || true
  exit 1
fi

if ! "$PY" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)"; then
  echo "需要 Python 3.9+，当前: $("$PY" -V)"
  read -r -p "按回车退出..." || true
  exit 1
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "首次启动：创建虚拟环境并安装协议依赖…"
  "$PY" -m venv "$VENV"
  "$VENV/bin/python" -m pip install -U pip
  "$VENV/bin/python" -m pip install -r "$ROOT/requirements-api.txt"
fi

export PYTHONPATH="$ROOT/algo:$ROOT"
URL="http://127.0.0.1:${PORT}/docs"
echo "启动服务: $URL  （Ctrl+C 停止）"
if command -v open >/dev/null 2>&1; then
  (sleep 2 && open "$URL") >/dev/null 2>&1 &
elif command -v xdg-open >/dev/null 2>&1; then
  (sleep 2 && xdg-open "$URL") >/dev/null 2>&1 &
fi

exec "$VENV/bin/python" -m uvicorn api.app:app --host 127.0.0.1 --port "$PORT" --workers 1
