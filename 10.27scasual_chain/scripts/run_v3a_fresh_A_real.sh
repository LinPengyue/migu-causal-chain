#!/usr/bin/env bash
# A (UAE vs Oman) one-shot real-API end-to-end integration.
# Run from a separate worktree on the server holding the original MP4.
# No API keys are stored in this script or written to the output manifest.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/10.27scasual_chain/algo${PYTHONPATH:+:$PYTHONPATH}"
export STORY_API_ENABLE=1

MATCH="10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语"
EVENTS="$REPO_ROOT/10.27scasual_chain/data/交付_out/${MATCH}.json"
CAUSAL="$REPO_ROOT/10.27scasual_chain/data/交付_out/${MATCH}_causal.json"
VIDEO="${V3A_OMAN_VIDEO:-/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4}"
HISTORY="${V3A_OMAN_HISTORY:-/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman}"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
OUT="${V3A_OMAN_OUT:-$HISTORY/fresh_e2e_A_real_$RUN_ID}"

for f in "$EVENTS" "$CAUSAL" "$VIDEO"; do
  if [[ ! -f "$f" ]]; then echo "ERROR missing input: $f" >&2; exit 2; fi
done
if [[ -e "$OUT" ]]; then echo "ERROR output exists: $OUT" >&2; exit 2; fi

# No key printing; ApiProvider performs a credential/model preflight before video processing.
if [[ -z "${STORY_LLM_BASE_URL:-${OPENAI_BASE_URL:-}}" || -z "${STORY_LLM_API_KEY:-${OPENAI_API_KEY:-}}" || -z "${STORY_LLM_MODEL:-${OPENAI_MODEL:-}}" ]]; then
  echo "ERROR Planner API env incomplete. Load secrets in the shell first (do not commit them)." >&2
  exit 2
fi
if [[ -z "${STORY_VLM_MODEL:-}" ]]; then
  echo "ERROR VLM model env incomplete." >&2
  exit 2
fi

python -m unittest discover -s 10.27scasual_chain/tests -p 'test_v3a_fresh_e2e.py' -v

echo "A match real API run; output: $OUT"
echo "3 rounds / at most 24 HTTP attempts / estimated USD 0.30 cap (not a hard billing cap)"
python -m story_video_agent_v3.fresh_e2e_cli \
  --match-id "$MATCH" \
  --events "$EVENTS" \
  --causal-atoms "$CAUSAL" \
  --video "$VIDEO" \
  --algo-root "$REPO_ROOT/10.27scasual_chain" \
  --history-root "$HISTORY" \
  --out-dir "$OUT" \
  --enable-real-api \
  --i-approve-budget \
  --max-rounds 3 \
  --max-calls 24 \
  --max-cost-usd 0.30 \
  --max-completion-tokens 2048

echo "SUMMARY: $OUT/fresh_e2e_summary.json"
echo "V3-R RAW: $OUT/01_to_04_fresh_v3r/04_phase5/story_clean.mp4"
echo "V3-A CANDIDATE: $OUT/06_candidate_render/story_clean.mp4"
