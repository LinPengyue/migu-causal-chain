#!/usr/bin/env bash
# Tests and prepares Story-First v2 evidence only. ZERO HTTP; no EDL edits.
set -euo pipefail
cd "$(dirname "$0")/.."
BRANCH="story-va-e2e-v2-story-first-20261114"
[[ "$(git branch --show-current)" == "$BRANCH" ]] || {
  echo "Wrong branch: expected $BRANCH" >&2
  exit 2
}
export PYTHONPATH="$PWD/algo"
export STORY_API_ENABLE=0
P14_EVENTS="$(printenv P14_EVENTS || true)"
[[ -n "$P14_EVENTS" ]] || { echo "Set P14_EVENTS to the REAL enriched events JSON" >&2; exit 2; }
P14_RUN="$(printenv P14_RUN || true)"
P14_RUN="$(printf '%s' "$P14_RUN")"
[[ -n "$P14_RUN" ]] || P14_RUN="/tmp/lpy1_v3a_p14_cv_integration_20261113/run"
P14_EDL="$(printenv P14_EDL || true)"
[[ -n "$P14_EDL" ]] || P14_EDL="$P14_RUN/01_initial_story/candidate_edl.json"
P14_PLAN="$(printenv P14_PLAN || true)"
[[ -n "$P14_PLAN" ]] || P14_PLAN="$P14_RUN/01_initial_story/story_plan.json"
OUT="$(printenv STORY_FIRST_OUT || true)"
[[ -n "$OUT" ]] || OUT="/tmp/lpy1_story_first_v2_prepared_20261114"
for f in "$P14_EDL" "$P14_EVENTS"; do
  [[ -s "$f" ]] || { echo "Missing input $f" >&2; exit 2; }
done
[[ ! -e "$OUT" ]] || { echo "Refusing existing output $OUT" >&2; exit 2; }
python -m pytest -q tests/test_v3a_story_first_poc.py
if [[ -s "$P14_PLAN" ]]; then
  python -m story_video_agent_v3.story_first_poc_cli \
    --edl "$P14_EDL" --events "$P14_EVENTS" \
    --story-plan "$P14_PLAN" --out-dir "$OUT"
else
  python -m story_video_agent_v3.story_first_poc_cli \
    --edl "$P14_EDL" --events "$P14_EVENTS" --out-dir "$OUT"
fi
git rev-parse HEAD > "$OUT/code_sha.txt"
python - "$OUT" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
audit = json.loads((root / "hypothesis_generation_audit.json").read_text())
hyp = json.loads((root / "story_hypotheses.json").read_text())
plan = json.loads((root / "observation_plan.json").read_text())
assert audit["http_attempts"] == 0
assert audit["status"] == "PREPARED_ONLY_ZERO_HTTP"
assert audit["edl_modified"] is False
assert audit["first_live_certified"] is False
assert hyp["hypotheses"] == []
assert plan["targets"] == []
print("ZERO_HTTP_STAGE1_PREPARED_ONLY", root)
print(json.dumps(audit["input_counts"], ensure_ascii=False, indent=2))
PY
echo "Auditable input/probe plan: $OUT"
