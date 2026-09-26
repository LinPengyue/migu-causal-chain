#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/algo:${ROOT}/eval${PYTHONPATH:+:$PYTHONPATH}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
MODEL_PATH="${MODEL_PATH:-./models/Qwen2.5-VL}"
STREAM_SOURCE="${STREAM_SOURCE:-timeline}"
EXTRA=()
if [[ "${RULE_ONLY:-0}" == "1" ]]; then
  EXTRA+=(--rule-only)
else
  EXTRA+=(--use-llm --model-path "$MODEL_PATH" --device cuda)
fi
if [[ "${SLIDING_RECALL:-0}" == "1" ]]; then
  EXTRA+=(--sliding-recall)
fi
if [[ -n "${LIMIT_MATCHES:-}" ]]; then
  EXTRA+=(--limit-matches "$LIMIT_MATCHES")
fi
if [[ -n "${PREFIX_STRIDE:-}" ]]; then
  EXTRA+=(--prefix-stride "$PREFIX_STRIDE")
fi
exec python -u eval/run_stream_strip.py \
  --stream-source "$STREAM_SOURCE" \
  "${EXTRA[@]}" \
  "$@"
