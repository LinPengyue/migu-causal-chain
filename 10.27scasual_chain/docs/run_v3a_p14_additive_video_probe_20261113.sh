#!/usr/bin/env bash
# Read-only P14 + current V3-A source-video-first opportunity search.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/algo"
export STORY_API_ENABLE=0

BRANCH=story-va-v3a-p14-additive-video-opportunity-20261113
[[ "$(git branch --show-current)" == "$BRANCH" ]] || { echo "Wrong branch, use isolated checkout"; exit 2; }
[[ -z "$(git status --porcelain)" ]] || { echo "Dirty tree, abort"; exit 2; }

ROOT=/tmp/lpy1_v3a_p14_cv_integration_20261113/run
PHASE5="$ROOT/01_to_04_fresh_v3r/04_phase5"
SRC='/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4'
EVENTS='data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json'
ENRICH="$ROOT/01_to_04_fresh_v3r/01_enrich/events_enriched.json"
OUT=${OUT_OVERRIDE:-/tmp/lpy1_v3a_p14_additive_probe_20261113}
for path in "$SRC" "$EVENTS" "$ENRICH" "$PHASE5/story_plan.json" \
  "$PHASE5/story_clean.mp4" "$PHASE5/candidate_edl.json"; do
  [[ -s "$path" ]] || { echo "Missing source: $path"; exit 2; }
done
[[ ! -e "$OUT" ]] || { echo "Refuse overwrite: $OUT"; exit 2; }

python -m pytest -q tests/test_v3a_additive_story_opportunity.py tests/test_v3a_additive_native_semantic.py
mkdir -p "$OUT"
git rev-parse HEAD > "$OUT/code_sha.txt"

python - "$SRC" "$EVENTS" "$PHASE5/candidate_edl.json" "$PHASE5/story_clean.mp4" "$OUT/input_checksums.json" <<'PY'
import hashlib, json, sys
from pathlib import Path
paths=list(map(Path,sys.argv[1:5]))
expected={"source":"a66147f79609c8fbf831a8bd29de4c6d7f746b314b2b18a88ffb1fc5f319da9c",
          "events":"ddae99b21cbfcd1c75ddf620d957578e57c2c013d607ac893655c4d52b7e779e"}
def digest(path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for part in iter(lambda:f.read(1024*1024),b""):h.update(part)
 return h.hexdigest()
d={name:digest(path) for name,path in zip(("source","events","edl","story"),paths)}
for name,value in expected.items(): assert d[name]==value,(name,d[name])
Path(sys.argv[5]).write_text(json.dumps(d,indent=2)+"\n")
print("SOURCE_AND_EVENTS_SHA_OK")
PY

# The production delivery might remain BLOCKED: that says nothing about
# diagnostic clip extraction. We check the additive probe independently.
set +e
python -m story_video_agent_v3.story_e2e_cli \
  --match-json "$EVENTS" --events-json "$ENRICH" \
  --source-mp4 "$SRC" --phase5-dir "$PHASE5" \
  --out-dir "$OUT/agent" --offline --max-rounds 1 \
  --enable-additive-story-probe --no-smoke-render \
  > "$OUT/agent.log" 2>&1
rc=$?
set -e

python - "$OUT" "$rc" "$PHASE5/candidate_edl.json" "$PHASE5/story_clean.mp4" <<'PY'
import json,hashlib,sys
from pathlib import Path
out=Path(sys.argv[1]); cli_exit=int(sys.argv[2])
def read(path): return json.loads(path.read_text()) if path.is_file() else {}
def digest(path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for part in iter(lambda:f.read(1024*1024),b""):h.update(part)
 return h.hexdigest()
before=read(out/"input_checksums.json")
unchanged=(digest(Path(sys.argv[3]))==before["edl"]
           and digest(Path(sys.argv[4]))==before["story"])
probe=read(out/"agent/02_round_01/additive_story_probe.json")
op=read(out/"agent/02_round_01/additive_opportunities.json")
pack=read(out/"agent/02_round_01/additive_opportunity_video_pack/opportunity_video_manifest.json")
audit=read(out/"agent/story_e2e_audit.json")
clips=[
 c for item in pack.get("review_items",[])
 for c in item.get("source_context_clips",[]) if c.get("export",{}).get("ok")
]
summary={
 "schema":"v3a_p14_additive_video_probe_check_v1",
 "code_sha":(out/"code_sha.txt").read_text().strip(),
 "input_mode":"FROZEN_P14_HUMAN_ATOM_DEV_REGRESSION",
 "cli_exit":cli_exit,
 "probe_status":probe.get("status"),
 "opportunity_count":len(op.get("opportunities",[])),
 "source_clip_count":len(clips),
 "source_windows":[[c["media_in"],c["media_out"]] for c in clips],
 "review_directory":str(out/"agent/02_round_01/additive_opportunity_video_pack"),
 "baseline_edl_mp4_unchanged":unchanged,
 "http_calls":audit.get("http_calls"),
 "first_live_verified":False,
 "story_quality_improved":False,
 "candidate_edl_mutated_by_probe":False,
 "formal_delivery":(audit.get("delivery") or {}).get("delivery_status"),
}
(out/"probe_report.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
print(json.dumps(summary,ensure_ascii=False,indent=2))
assert unchanged,"FROZEN_P14_CHANGED"
assert audit.get("http_calls",0) == 0,"UNEXPECTED_PAID_CALL"
assert probe.get("status") == "VIDEO_PACK_EXPORTED_NOT_SEMANTICALLY_REVIEWED", "NO_VALID_VIDEO_PACK"
assert 1 <= len(clips) <= 4,"NO_SOURCE_VIDEO_CLIPS"
assert all(c.get("semantic_fit_verified") is False
           and c.get("first_live_verified") is False for c in clips),"UNVERIFIED_CLAIM"
PY
echo "Review pack: $OUT/agent/02_round_01/additive_opportunity_video_pack"
echo "Machine report: $OUT/probe_report.json"
