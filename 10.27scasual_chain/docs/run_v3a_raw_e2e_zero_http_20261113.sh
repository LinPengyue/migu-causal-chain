#!/usr/bin/env bash
# V3-A fresh RAW-only MP4+events main-chain experiment, NO PAID REQUESTS.
# Execute only on the existing Migu VIDEO server with original full MP4.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

BRANCH="story-va-v3a-critic-verifier-increment-20261113"
MIN_COMMIT="ec0de76834973ffd4e38b4c541461ce70f7ee203"
SOURCE_MP4="/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4"
EVENTS_JSON="/data2/lpy1/worktrees/migu-v3a-p11-verify/10.27scasual_chain/data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json"
SOURCE_SHA="a66147f79609c8fbf831a8bd29de4c6d7f746b314b2b18a88ffb1fc5f319da9c"
EVENTS_SHA="ddae99b21cbfcd1c75ddf620d957578e57c2c013d607ac893655c4d52b7e779e"

# Allow explicit path overrides ONLY if their contents match frozen SHA.
SOURCE_MP4="${SOURCE_MP4_OVERRIDE:-$SOURCE_MP4}"
EVENTS_JSON="${EVENTS_JSON_OVERRIDE:-$EVENTS_JSON}"
OUT="${OUT_OVERRIDE:-/tmp/lpy1_v3a_cv_raw_e2e_20261113_first_run}"

[[ -f "$SOURCE_MP4" ]] || { echo "ERROR source video unavailable: $SOURCE_MP4" >&2; exit 2; }
[[ -f "$EVENTS_JSON" ]] || { echo "ERROR raw event JSON unavailable: $EVENTS_JSON" >&2; exit 2; }
[[ ! -e "$OUT" ]] || { echo "ERROR refuse overwrite: $OUT" >&2; exit 2; }
[[ "$(git branch --show-current)" == "$BRANCH" ]] || {
    echo "ERROR wrong branch: expected $BRANCH" >&2; exit 2;
}
git merge-base --is-ancestor "$MIN_COMMIT" HEAD || {
    echo "ERROR required Critic/Verifier integration commit absent" >&2; exit 2;
}
[[ -z "$(git status --porcelain)" ]] || {
    echo "ERROR worktree is dirty; preserve reproducibility" >&2; exit 2;
}
command -v ffmpeg >/dev/null
command -v ffprobe >/dev/null
command -v python >/dev/null
python - <<'PY'
import sys
print("Python:", sys.version.split()[0])
PY

ACT_SOURCE_SHA="$(sha256sum "$SOURCE_MP4" | awk '{print $1}')"
ACT_EVENTS_SHA="$(sha256sum "$EVENTS_JSON" | awk '{print $1}')"
[[ "$ACT_SOURCE_SHA" == "$SOURCE_SHA" ]] || {
    echo "ERROR source MP4 SHA mismatch: $ACT_SOURCE_SHA" >&2; exit 2;
}
[[ "$ACT_EVENTS_SHA" == "$EVENTS_SHA" ]] || {
    echo "ERROR raw events SHA mismatch: $ACT_EVENTS_SHA" >&2; exit 2;
}

# This is NOT an artificial B1 broken EDL, not annotated atoms, and not an
# archival Phase5 reuse. Leave no protected output touched.
mkdir -p "$OUT"
printf '%s\n' "$(git rev-parse HEAD)" > "$OUT/experiment_code_sha.txt"
printf '%s\n' "$ACT_SOURCE_SHA" > "$OUT/input_source_mp4_sha256.txt"
printf '%s\n' "$ACT_EVENTS_SHA" > "$OUT/input_events_json_sha256.txt"

echo "Starting strictly raw-only full V3-R → V3-A (ZERO HTTP)."
set +e
STORY_API_ENABLE=0 PYTHONPATH=.:algo python -m story_video_agent_v3.story_full_e2e_cli \
  --source-mp4 "$SOURCE_MP4" \
  --events-json "$EVENTS_JSON" \
  --strict-raw-only \
  --match-id uae_oman_raw_only_20261113 \
  --max-rounds 1 \
  --no-smoke-render \
  --out-dir "$OUT" \
  > "$OUT/full_e2e_stdout.txt" 2>&1
RC=$?
set -e
printf '%s\n' "$RC" > "$OUT/experiment_exit_code.txt"

# Produce a compact audit even on a blocked/partial run. No fabricated PASS.
OUT_DIR="$OUT" RUN_RC="$RC" PYTHONPATH=.:algo python - <<'PY'
from pathlib import Path
import os, json, hashlib
from story_video_agent_v3.story_timeline import edl_rows

root=Path(os.environ["OUT_DIR"])
def load(p):
    try:
        f=root/p
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except Exception as exc:
        return {"read_error": str(exc)}
def sha(p):
    if not p.is_file():
        return None
    h=hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda:f.read(2**20),b""):h.update(c)
    return h.hexdigest()
def edl_summary(p):
    x=load(p)
    if x is None:
        return {"present": False}
    try: rows=edl_rows(x)
    except Exception as exc: return {"present": True, "parse_error": str(exc)}
    active=[r for r in rows if r.get("include_in_cut",True)]
    goals=[r for r in active if "goal_action" in str(r.get("role") or "").lower()]
    return {
      "present": True, "n_active": len(active),
      "goal_action_rows": [{
        "segment_id":r.get("segment_id"),"role":r.get("role"),
        "media_in":r.get("media_in"),"media_out":r.get("media_out"),
        "first_live_status":r.get("first_live_status"),
        "is_replay":r.get("is_replay"),
      } for r in goals],
      "n_explicit_replay_rows":sum(r.get("is_replay") is True for r in active),
    }
phase5="01_to_04_fresh_v3r/04_phase5"
round1="02_round_01"
diag=load(round1+"/story_diagnosis.json") or {}
v=load(round1+"/verifier_report.json") or {}
audit=load("story_e2e_audit.json") or {}
summary=load("full_e2e_summary.json") or {}
initial=root/"01_initial_story/story_clean.mp4"
phase5mp4=root/(phase5+"/story_clean.mp4")
candidate=root/(round1+"/candidate_render/story_clean.mp4")
result={
 "schema":"v3a_cv_zero_http_raw_e2e_audit_v1",
 "run_exit_code":int(os.environ["RUN_RC"]),
 "code_sha":(root/"experiment_code_sha.txt").read_text().strip(),
 "raw_only_input_contract":load("00_full_e2e_contract.json"),
 "full_e2e_summary":summary,
 "phase5_v3r_edl":edl_summary(phase5+"/candidate_edl.json"),
 "initial_v3r_edl":edl_summary("01_initial_story/candidate_edl.json"),
 "initial_video": {
   "phase5_present":phase5mp4.is_file(),"phase5_sha256":sha(phase5mp4),
   "staged_present":initial.is_file(),"staged_sha256":sha(initial),
 },
 "critic": {
   "issue_categories":[{"id":x.get("issue_id"),"category":x.get("category"),
     "diagnosis_status":x.get("diagnosis_status")} for x in diag.get("issues",[])
     if isinstance(x,dict)],
   "goal_video_critic_handoff":diag.get("goal_video_critic_handoff"),
   "n_issues":len(diag.get("issues") or []),
 },
 "verifier": {
   "present":bool(v),
   "business_first_live_review":v.get("business_first_live_review"),
   "candidate_accepted":v.get("candidate_accepted"),
   "hard_vetoes":v.get("hard_vetoes"),
   "phase8_verdict":v.get("phase8_verdict"),
 },
 "candidate_video":{"present":candidate.is_file(),"sha256":sha(candidate)},
 "http_calls":audit.get("http_calls"),
 "delivery":audit.get("delivery"),
 "safety_disclaimer":"Offline run cannot test VLM semantic understanding or establish first-live or video quality.",
}
dest=root/"cv_raw_e2e_audit.json"
dest.write_text(json.dumps(result,indent=2,ensure_ascii=False,default=str)+"\n",encoding="utf-8")
print("Audit:",dest)
print("Exit:",result["run_exit_code"])
print("Initial:",result["initial_video"])
print("Critic issues:",result["critic"]["n_issues"])
print("Verifier:",result["verifier"]["business_first_live_review"])
print("HTTP:",result["http_calls"])
PY

echo "Raw E2E return code: $RC"
echo "Artifacts: $OUT"
echo "NOTE: video story quality and first-live remain unverified until source-video review."
exit "$RC"
