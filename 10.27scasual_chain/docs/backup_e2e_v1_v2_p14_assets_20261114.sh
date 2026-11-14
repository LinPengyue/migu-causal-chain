#!/usr/bin/env bash
# Optional server backup of non-Git P14 inputs; no network, overwrites or paid calls.
set -euo pipefail
cd "$(dirname "$0")/.."
P14_EVENTS="$(printenv P14_EVENTS || true)"
E2E_BACKUP_ROOT="$(printenv E2E_BACKUP_ROOT || true)"
[[ -n "$P14_EVENTS" && -n "$E2E_BACKUP_ROOT" ]] || {
 echo "Specify P14_EVENTS and E2E_BACKUP_ROOT" >&2; exit 2;
}
P14_RUN="$(printenv P14_RUN || true)"
[[ -n "$P14_RUN" ]] || P14_RUN="/tmp/lpy1_v3a_p14_cv_integration_20261113/run"
P14_EDL="$(printenv P14_EDL || true)"
[[ -n "$P14_EDL" ]] || P14_EDL="$P14_RUN/01_initial_story/candidate_edl.json"
P14_PLAN="$(printenv P14_PLAN || true)"
[[ -n "$P14_PLAN" ]] || P14_PLAN="$P14_RUN/01_initial_story/story_plan.json"
P14_STORY="$(printenv P14_STORY || true)"
[[ -n "$P14_STORY" ]] || P14_STORY="$P14_RUN/01_initial_story/story_clean.mp4"
SRC_MP4="$(printenv SRC_MP4 || true)"
[[ ! -e "$E2E_BACKUP_ROOT" ]] || { echo "Refusing existing backup directory" >&2; exit 2; }
for f in "$P14_EVENTS" "$P14_EDL"; do
 [[ -s "$f" ]] || { echo "Missing required asset: $f" >&2; exit 2; }
done
mkdir -p "$E2E_BACKUP_ROOT"
cp -p -- "$P14_EVENTS" "$E2E_BACKUP_ROOT/enriched_events.json"
cp -p -- "$P14_EDL" "$E2E_BACKUP_ROOT/v3r_candidate_edl.json"
if [[ -s "$P14_PLAN" ]]; then cp -p -- "$P14_PLAN" "$E2E_BACKUP_ROOT/v3r_story_plan.json"; fi
if [[ -s "$P14_STORY" ]]; then cp -p -- "$P14_STORY" "$E2E_BACKUP_ROOT/v3r_story_clean.mp4"; fi
python - "$E2E_BACKUP_ROOT" "$P14_EVENTS" "$P14_EDL" "$P14_PLAN" "$P14_STORY" "$SRC_MP4" <<'PY'
import hashlib, json, subprocess, sys
from pathlib import Path
out = Path(sys.argv[1])
keys = ["events_original","edl_original","story_plan_original","story_mp4_original","source_mp4_original"]
orig = {k:Path(v) if v else None for k,v in zip(keys,sys.argv[2:])}
def sha(p):
 h = hashlib.sha256()
 with p.open("rb") as f:
  for chunk in iter(lambda:f.read(4*1024*1024),b""):h.update(chunk)
 return h.hexdigest()
copies = {}
for p in sorted(out.iterdir()):
 if p.is_file():
  copies[p.name] = {"sha256":sha(p),"size":p.stat().st_size}
def git(ref):
 try: return subprocess.check_output(["git","rev-parse",ref],text=True,stderr=subprocess.DEVNULL).strip()
 except Exception: return None
video = orig["source_mp4_original"]
record = {
 "schema":"migu_e2e_v1_v2_server_assets_backup_v1",
 "data_tier":"HUMAN_ATOM_ENRICHED_DEV",
 "v1_branch":"story-va-e2e-v1-frozen-20261114",
 "v1_branch_sha":git("origin/story-va-e2e-v1-frozen-20261114"),
 "v2_branch":"story-va-e2e-v2-story-first-20261114",
 "v2_branch_sha":git("origin/story-va-e2e-v2-story-first-20261114"),
 "common_code_base_sha":"fe4c618e85786cc6197adfa886e1bad75a87d97e",
 "copy_contents":copies,
 "original_paths":{k:str(v) if v else None for k,v in orig.items()},
 "source_video_copied":False,
 "source_video_sha256":sha(video) if video and video.is_file() else None,
 "first_live_certified":False,
 "edl_modified":False,
 "note":"Git branch snapshots and non-Git P14 DEV assets. Input video is referenced by hash, NOT copied."
}
(out/"backup_manifest.json").write_text(
 json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"backup":str(out),"files":list(copies),"video_sha_recorded":bool(record["source_video_sha256"])},ensure_ascii=False))
PY
echo "Non-Git P14 backup complete: $E2E_BACKUP_ROOT"
