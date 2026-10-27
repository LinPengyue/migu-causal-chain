#!/usr/bin/env bash
# 打包 8.31causal_chain 上传服务器（不含 Qwen 权重）
# 默认排除 reports 下 reel/日志以减小体积；需要复现重算时可 PACK_WITH_REELS=1
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PARENT="$(dirname "$ROOT")"
NAME="$(basename "$ROOT")"
OUT="${PARENT}/${NAME}_bundle.tar.gz"

EXCLUDES=(
  --exclude="${NAME}/reports/*.log"
  --exclude="${NAME}/**/__pycache__"
  --exclude="${NAME}/**/*.pyc"
  --exclude="${NAME}/algo/**/_checkpoints"
)
if [[ "${PACK_WITH_REELS:-0}" != "1" ]]; then
  EXCLUDES+=(--exclude="${NAME}/reports/reels")
  EXCLUDES+=(--exclude="${NAME}/reports/reels_llm_assist")
fi

cd "$PARENT"
tar -czf "$OUT" "${EXCLUDES[@]}" "$NAME"
echo "wrote $OUT"
ls -lh "$OUT"
