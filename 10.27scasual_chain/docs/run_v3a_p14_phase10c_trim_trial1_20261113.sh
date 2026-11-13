#!/usr/bin/env bash
# One ZERO-HTTP, reversible quality hypothesis using existing Phase10-C sandbox.
# NOTE: a DEV-only FIXTURE proposes the edit, not an autonomous model.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/algo"
export STORY_API_ENABLE=0
[[ "$(git branch --show-current)" == "story-va-v3a-p14-story-quality-20261113" ]] || {
  echo "Wrong branch: refuse modifying another worktree"; exit 2;
}
[[ -z "$(git status --porcelain)" ]] || {
  echo "Dirty worktree: use a clean dedicated checkout"; exit 2;
}
ROOT=/tmp/lpy1_v3a_p14_cv_integration_20261113/run
PHASE5="$ROOT/01_to_04_fresh_v3r/04_phase5"
INITIAL="$ROOT/01_initial_story"
SRC="/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4"
EVENTS="data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json"
ENRICH="$ROOT/01_to_04_fresh_v3r/01_enrich/events_enriched.json"
OUT=${OUT_OVERRIDE:-/tmp/lpy1_v3a_p14_phase10_c_trim_trial1_20261113}
for p in "$SRC" "$EVENTS" "$ENRICH" "$PHASE5/candidate_edl.json" \
  "$PHASE5/story_clean.mp4" "$PHASE5/story_plan.json" \
  "$ROOT/02_round_01/story_diagnosis.json"; do
  [[ -s "$p" ]] || { echo "Input not found: $p"; exit 2; }
done
[[ ! -e "$OUT" ]] || { echo "Refuse existing output: $OUT"; exit 2; }
mkdir -p "$OUT"
python - "$PHASE5/candidate_edl.json" \
    "$ROOT/02_round_01/story_diagnosis.json" "$OUT/fixture_proposal.json" \
    "$SRC" "$PHASE5/story_clean.mp4" "$EVENTS" <<'PY'
import hashlib, json, sys
from pathlib import Path
from story_video_agent_v3.story_timeline import edl_rows
edl_path, diag_path, proposal_path, source, baseline, events = map(Path, sys.argv[1:])
def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()
source_sha = digest(source)
events_sha = digest(events)
assert source_sha == "a66147f79609c8fbf831a8bd29de4c6d7f746b314b2b18a88ffb1fc5f319da9c", "different_source_video"
assert events_sha == "ddae99b21cbfcd1c75ddf620d957578e57c2c013d607ac893655c4d52b7e779e", "different_raw_events"
edl = [x for x in edl_rows(json.loads(edl_path.read_text())) if x.get("include_in_cut", True)]
roles = [str(x.get("role") or "") for x in edl]
assert sum("goal_action" in r for r in roles) == 3, "not_three_goal_baseline"
assert all(r in roles for r in ("opponent_opening_goal_action","equalizer_goal_action","go_ahead_goal_action"))
turn = [i for i,x in enumerate(edl) if x.get("role")=="equalizer_goal_action"]
assert len(turn)==1, "expected_one_equalizer"
ix=turn[0]
assert ix>=1 and edl[ix-1].get("role")=="buildup_action", "not_adjacent_buildup_to_turn"
target=edl[ix-1]
s_id,goal_id=str(target["segment_id"]),str(edl[ix]["segment_id"])
issues=json.loads(diag_path.read_text()).get("issues") or []
matches=[i for i in issues if i.get("category")=="transition"
         and s_id in (i.get("segment_ids") or [])
         and goal_id in (i.get("segment_ids") or [])]
assert matches, "transition_issue_not_present"
lo,hi=float(target["media_in"]),float(target["media_out"])
duration=hi-lo
assert 7 <= duration <= 60, "unsupported_trim_duration"
new_hi=round(hi-0.25*duration,3)
assert new_hi-lo>=2 and (new_hi-lo)/duration>=0.45
proposal={
    "action":"trim",
    "target_segment_id":s_id,
    "media_in":lo,
    "media_out":new_hi,
    "hypothesis":"The tail of the previous buildup shot might misleadingly imply direct causal continuity into a much later equalizer; this needs blind comparison, not a factual defect claim.",
    "expected_effect":"Test whether omitting the final quarter of this pre-equalizer buildup shot reduces false causal adjacency while keeping the story understandable.",
    "risk":"Removing the tail can weaken suspense and remove genuine buildup information; an equal-duration shorter film is not automatically better.",
}
proposal_path.write_text(json.dumps({"proposal":proposal},ensure_ascii=False,indent=2)+"\n")
(proposal_path.parent/"trial_input_sha.json").write_text(json.dumps({
 "source_sha256":source_sha,"events_sha256":events_sha,
 "baseline_edl_sha256":digest(edl_path),"baseline_mp4_sha256":digest(baseline),
 "hypothesis_issue_id":matches[0].get("issue_id"),
 "baseline_n_goals":3,"fixture_source":"HUMAN_PROPOSED_NOT_AUTONOMOUS_AGENT",
 "target_segment_id":s_id,"original_window":[lo,hi],
 "proposed_window":[lo,new_hi],"paid_http":0,
},ensure_ascii=False,indent=2)+"\n")
print("DEV HYPOTHESIS",s_id,"original",lo,hi,"trial",lo,new_hi)
PY
git rev-parse HEAD > "$OUT/code_sha.txt"
set +e
python -m story_video_agent_v3.story_e2e_cli \
  --match-json "$EVENTS" --events-json "$ENRICH" \
  --source-mp4 "$SRC" --phase5-dir "$PHASE5" \
  --out-dir "$OUT/agent" --offline --max-rounds 1 --no-smoke-render \
  --phase10-explore --phase10-explore-fixture "$OUT/fixture_proposal.json" \
  > "$OUT/agent.log" 2>&1
rc=$?
set -e
python - "$OUT" "$rc" "$PHASE5/candidate_edl.json" "$PHASE5/story_clean.mp4" <<'PY'
import hashlib,json,sys
from pathlib import Path
out=Path(sys.argv[1]); rc=int(sys.argv[2])
p=out/"agent/02_round_01/phase10_exploratory/exploratory_trial.json"
e=json.loads(p.read_text()) if p.is_file() else {}
before=json.loads((out/"trial_input_sha.json").read_text())
def sha(path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
 return h.hexdigest()
unchanged=(sha(Path(sys.argv[3]))==before["baseline_edl_sha256"] and
           sha(Path(sys.argv[4]))==before["baseline_mp4_sha256"])
assert unchanged,"FROZEN_P14_BASELINE_CHANGED"
audit_path=out/"agent/story_e2e_audit.json"
audit=json.loads(audit_path.read_text()) if audit_path.is_file() else {}
report={
 "schema":"v3a_p14_phase10c_trim_trial1_audit_v1",
 "code_sha":(out/"code_sha.txt").read_text().strip(),
 "cli_exit":rc,
 "hypothesis_source":"OFFLINE_FIXTURE_NOT_AGENT_AUTONOMOUS",
 "phase10_status":e.get("status"),
 "phase10_reason":e.get("reason"),
 "candidate_rendered":bool(e.get("candidate_rendered")),
 "blind_pair_status":e.get("blind_pair_status"),
 "blind_review_dir":e.get("blind_review_dir"),
 "candidate_mp4":e.get("candidate_mp4"),
 "baseline_unchanged":unchanged,
 "new_source_windows":e.get("new_source_windows"),
 "formal_revision_applied":e.get("formal_revision_applied"),
 "release_authorized":e.get("release_authorized"),
 "promote_best":e.get("promote_best"),
 "http_calls":audit.get("http_calls"),
 "quality_improved_claimed":False,
 "first_live_verified_claimed":False,
 "note":"Phase10 is separate from Planner/Verifier/BEST; read PRIVATE_unblinding only after blind review. First-live of inherited P14 footage remains unresolved.",
}
(out/"trial1_result.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
print(json.dumps(report,indent=2,ensure_ascii=False))
if e.get("status")!="EXPLORATORY_RENDERED_NOT_VERIFIED" or not e.get("candidate_rendered"):
 print("NO_BLIND_PAIR: inspect agent.log and exploratory_trial.json",file=sys.stderr)
 sys.exit(3)
if audit.get("http_calls") not in (0,None) or e.get("release_authorized") or e.get("promote_best"):
 sys.exit("SAFETY_INVARIANT_FAILED")
PY
echo "Trial result: $OUT/trial1_result.json"
echo "Blind pair: $OUT/agent/02_round_01/phase10_exploratory/blind_review/{X,Y}.mp4"
