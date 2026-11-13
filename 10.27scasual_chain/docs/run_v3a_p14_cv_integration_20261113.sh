#!/usr/bin/env bash
# P14 human-atom DEV baseline + latest V3-A Critic/Verifier, zero paid calls.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/algo"
export STORY_API_ENABLE=0
branch=$(git branch --show-current)
[[ "$branch" == "story-va-v3a-p14-story-quality-20261113" ]] || { echo "Wrong branch: $branch"; exit 2; }
[[ -z "$(git status --porcelain)" ]] || { echo "Dirty worktree; abort"; exit 2; }
MP4="${SOURCE_MP4_OVERRIDE:-/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4}"
EVENTS="${EVENTS_JSON_OVERRIDE:-data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json}"
CAUSAL="${CAUSAL_JSON_OVERRIDE:-data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语_causal.json}"
OUT="${OUT_OVERRIDE:-/tmp/lpy1_v3a_p14_cv_integration_20261113}"
for f in "$MP4" "$EVENTS" "$CAUSAL"; do [[ -s "$f" ]] || { echo "Missing: $f"; exit 2; }; done
[[ ! -e "$OUT" ]] || { echo "Output exists, refuse overwrite: $OUT"; exit 2; }
python - "$MP4" "$EVENTS" <<'PY'
import hashlib,sys
expected=["a66147f79609c8fbf831a8bd29de4c6d7f746b314b2b18a88ffb1fc5f319da9c","ddae99b21cbfcd1c75ddf620d957578e57c2c013d607ac893655c4d52b7e779e"]
for p,exp in zip(sys.argv[1:],expected):
 h=hashlib.sha256()
 with open(p,"rb") as f:
  for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
 assert h.hexdigest()==exp,(p,h.hexdigest())
 print("INPUT_SHA_OK",p,h.hexdigest())
PY
mkdir -p "$OUT"
git rev-parse HEAD > "$OUT/code_sha.txt"
set +e
python -m story_video_agent_v3.story_full_e2e_cli \
 --source-mp4 "$MP4" --events-json "$EVENTS" --causal-json "$CAUSAL" \
 --out-dir "$OUT/run" --max-rounds 1 \
 > "$OUT/full_e2e.log" 2>&1
rc=$?
set -e
python - "$OUT" "$rc" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]); rc=int(sys.argv[2]); run=root/"run"
def read(p):
 try:return json.loads(p.read_text())
 except Exception:return {}
edl=read(run/"01_to_04_fresh_v3r/04_phase5/candidate_edl.json")
recovery=read(run/"01_to_04_fresh_v3r/03_v1_adapt/goal_recovery.json")
audit=read(run/"story_e2e_audit.json")
def rows(x):
 if isinstance(x,list):return x
 if isinstance(x,dict):
  for k in ("segments","edl","rows","clips"):
   if isinstance(x.get(k),list):return x[k]
 return []
roles=[str(x.get("role","")) for x in rows(edl) if isinstance(x,dict)]
rounds=audit.get("rounds") or []
report={"schema":"v3a_p14_cv_integration_check_v1","mode":"HUMAN_ATOM_ENRICHED_DEV","formal_raw_only_benchmark":False,"cli_exit":rc,"source_code_sha":(root/"code_sha.txt").read_text().strip(),"goal_recovery_n_with_goal_action_sec":recovery.get("n_with_goal_action_sec"),"goal_roles":roles,"three_goal_roles_present":all(x in roles for x in ("opponent_opening_goal_action","equalizer_goal_action","go_ahead_goal_action")),"initial_mp4_exists":(run/"01_to_04_fresh_v3r/04_phase5/story_clean.mp4").is_file(),"agent_round_count":len(rounds),"round_dirs":[p.name for p in sorted(run.glob("02_round_*"))],"http_calls":audit.get("http_calls"),"cost":audit.get("est_cost_usd"),"final_delivery":audit.get("delivery"),"warning":"first-live unverified; P14 human annotations are DEV input; no automatic quality improvement claim"}
(root/"integration_check.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
PY
echo "CLI exit: $rc; check $OUT/integration_check.json and $OUT/full_e2e.log"
exit "$rc"
