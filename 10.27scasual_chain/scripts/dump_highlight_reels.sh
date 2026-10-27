#!/usr/bin/env bash
# 独立导出每场完整集锦（新增脚本，不改现有评测）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/algo:${ROOT}/eval${PYTHONPATH:+:$PYTHONPATH}"

OUT_DIR="${OUT_DIR:-reports/reels_dump}"
LIMIT="${LIMIT_MATCHES:-0}"

exec python -u eval/dump_highlight_reels.py \
  --out-dir "$OUT_DIR" \
  --limit-matches "$LIMIT" \
  "$@"
