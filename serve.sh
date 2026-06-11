#!/usr/bin/env bash
# serve.sh — 选校罗盘 Web 服务（API + 静态页同进程）
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
mkdir -p logs
exec uvicorn api.main:app --host 0.0.0.0 --port "$PORT" --app-dir "$(pwd)" --access-log >> logs/web.log 2>&1
