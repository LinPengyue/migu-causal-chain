#!/usr/bin/env bash
# Reuse P14 Phase5, run current V3-A once, export proactive TURN context,
# zero HTTP, no release, no EDL overwrite.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "$(git branch --show-current)" == "story-va-v3a-p14-story-quality-20261113" ]] || {
 echo "Wrong branch"; exit 2;
}
[[ -z "$(git status --porcelain)" ]] || { echo "Dirty source checkout"; exit 2; }
export PYTHONPATH="$PWD/algo"
export STORY_API_ENABLE=0
SRC="/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4"
EVENTS="data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json"
P14="/tmp/lpy1_v3a_p14_cv_integration_20261113/run"
PHASE5="$P14/01_to_04_fresh_v3r/04_phase5"
ENRICH="$P14/01_to_04_fresh_v3r/01_enrich/events_enriched.json"
OUT="${OUT_OVERRIDE:-/tmp/lpy1_v3a_p14_proactive_turn_20261113}"
[[ ! -e "$OUT" ]] || { echo "Refusing existing output $OUT"; exit 2; }
for f in "$SRC" "$EVENTS" "$ENRICH" "$PHASE5/candidate_edl.json" "$PHASE5/story_clean.mp4"; do
 [[ -s "$f" ]] || { echo "Missing input $f"; exit 2; }
done
python -m pytest -q tests/test_v3a_turn_context_search.py
mkdir -p "$OUT"
git rev-parse HEAD > "$OUT/code_sha.txt"
# The formal main-chain CLI returns nonzero for BLOCKED (expected). We independently
# inspect the new review artifact to decide whether the observation experiment ran.
set +e
python -m story_video_agent_v3.story_e2e_cli \
 --match-json "$EVENTS" --source-mp4 "$SRC" \
 --phase5-dir "$PHASE5" --events-json "$ENRICH" \
 --out-dir "$OUT/agent" --offline --max-rounds 1 --no-smoke-render \
 > "$OUT/agent.log" 2>&1
rc=$?
set -e
echo "$rc" > "$OUT/formal_cli_exit.txt"
SEARCH="$OUT/agent/02_round_01/proactive_turn_context_search.json"
[[ -s "$SEARCH" ]] || { echo "No proactive-turn output; inspect $OUT/agent.log"; exit 3; }
python docs/export_v3a_turn_context_video.py \
 --run-dir "$OUT/agent" --source-mp4 "$SRC" \
 --out-dir "$OUT/proactive_video_review" --top-k 4
python - "$OUT" <<'PY'
from pathlib import Path
import json, sys
p=Path(sys.argv[1]); run=p/"agent"
j=json.loads((run/"02_round_01/proactive_turn_context_search.json").read_text())
audit=json.loads((run/"story_e2e_audit.json").read_text())
p14=Path("/tmp/lpy1_v3a_p14_cv_integration_20261113/run")
import hashlib
def sha(f):
 h=hashlib.sha256()
 with open(f,"rb") as r:
  for b in iter(lambda:r.read(1024*1024),b""):h.update(b)
 return h.hexdigest()
phase=p14/"01_to_04_fresh_v3r/04_phase5"
baseline_edl=phase/"candidate_edl.json"
baseline_mp4=phase/"story_clean.mp4"
assert baseline_edl.is_file() and baseline_mp4.is_file()
original=json.loads((p14/"story_e2e_audit.json").read_text())
assert audit.get("http_calls")==0, audit.get("http_calls")
assert audit.get("source_sha256")==original.get("source_sha256")
assert j.get("mode")=="OBSERVATION_ONLY"
assert j.get("first_live_certified") is False
assert j.get("no_edl_write") is True
targets=j.get("targets") or []
# No hardcoded goal/clock assertions; output can legitimately be empty for other matches.
review=json.loads((p/"proactive_video_review/review_manifest.json").read_text())
assert review.get("paid_http")==0 and review.get("edl_modified") is False
r={"schema":"v3a_proactive_story_context_smoke_v1",
   "code_sha":(p/"code_sha.txt").read_text().strip(),
   "formal_cli_exit":int((p/"formal_cli_exit.txt").read_text()),
   "target_count":len(targets),
   "event_probes":sum(len(x.get("ranked_event_probes") or []) for x in targets),
   "video_review_targets":len(review.get("targets") or []),
   "http_calls":audit["http_calls"],
   "baseline_edl_sha256":sha(baseline_edl),"baseline_mp4_sha256":sha(baseline_mp4),
   "candidate_rendered":False,"edl_modified":False,"release_authorized":False,
   "quality_improved_claimed":False,"first_live_certified":False,
   "note":"DEV mode using P14-enriched events. Search output only, not new edited video."}
(p/"result.json").write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n")
print(json.dumps(r,ensure_ascii=False,indent=2))
PY
echo "Review clips and manifest: $OUT/proactive_video_review/"
