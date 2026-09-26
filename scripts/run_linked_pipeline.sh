#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/algo:${ROOT}/eval${PYTHONPATH:+:$PYTHONPATH}"
LIMIT="${LIMIT_MATCHES:-0}"
exec python -u eval/run_linked_pipeline.py --limit-matches "$LIMIT" "$@"
