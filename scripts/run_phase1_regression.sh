#!/usr/bin/env bash
# P3：Phase1 拆条回归（offline → B → A）
# 冻结口径：production = sliding_merge_mode=none + sliding_post_nms=off
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/algo:${ROOT}/eval${PYTHONPATH:+:$PYTHONPATH}"

EXTRA=()
if [[ "${SKIP_RUN:-0}" == "1" ]]; then
  EXTRA+=(--skip-run)
fi
if [[ -n "${LIMIT_MATCHES:-}" ]]; then
  EXTRA+=(--limit-matches "$LIMIT_MATCHES")
fi
if [[ -n "${REPORT:-}" ]]; then
  EXTRA+=(--report "$REPORT")
fi

exec python -u eval/run_phase1_regression.py \
  --profile "${PROFILE:-production}" \
  --baseline "${BASELINE:-reports/baseline_phase1_frozen.json}" \
  "${EXTRA[@]}" \
  "$@"
