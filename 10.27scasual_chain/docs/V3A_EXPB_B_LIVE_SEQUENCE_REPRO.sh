#!/usr/bin/env bash
# Exp B — zero-HTTP live-sequence audit for match B (diagnostic windows only).
# Does NOT call paid APIs, does NOT rerun Stage1–7, does NOT edit EDL/BEST.
set -euo pipefail
cd "$(dirname "$0")/.."

git fetch origin story-va-v3a-p17-native-broadcast-observer
git switch story-va-v3a-p17-native-broadcast-observer
git pull --ff-only

B=/tmp/lpy1_v3a_blind_repair_B_historical_20261112
EVENTS="$B/agent_input/events.json"
SRC="/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4"
OUT=/tmp/lpy1_v3a_p17_expB_live_sequence_20261113
mkdir -p "$OUT"

test -s "$EVENTS"
test -s "$SRC"
test -d /tmp/lpy1_v3a_stage3_B_real_video_qwen37_newkey_20261113_newkey
test -d /tmp/lpy1_v3a_stage4_B_first_live_review_fullctx_20261113
test -d /tmp/lpy1_v3a_stage5_B_temporal_audit_20261113
test -d /tmp/lpy1_v3a_stage6_B_video_first_20261113
test -d /tmp/lpy1_v3a_stage7_B_temporal_20261113

PYTHONPATH=algo python - <<'PY'
"""Reproduce Exp B window counts + verdict skeleton (zero HTTP)."""
import json
from pathlib import Path
from collections import Counter

EVENTS = Path("/tmp/lpy1_v3a_blind_repair_B_historical_20261112/agent_input/events.json")
raw = json.loads(EVENTS.read_text(encoding="utf-8"))
WINDOWS = {
    "pre": (6380.0, 6447.0),
    "action": (6447.0, 6465.0),
    "post": (6465.0, 6550.0),
}
SHOT_MIN, NET = 6447.2, 6450.6

def overlaps(ev, a, b):
    mt = ev["media_time"]
    ts, te = float(mt["start_time_sec"]), float(mt["end_time_sec"])
    return not (te < a or ts > b)

rows = []
for ev in raw["events"]:
    mt = ev["media_time"]
    rows.append({
        "id": ev["event_id"],
        "t": float(mt["event_time_sec"]),
        "type": ev["event_type"],
        "zh": ev["event_type_zh"],
        "replay": ev["video_context"]["is_replay"],
        "score": (ev.get("scores") or {}).get("score_recognition"),
    })

for name, (a, b) in WINDOWS.items():
    hit = [ev for ev in raw["events"] if overlaps(ev, a, b)]
    print(name, len(hit), Counter(e["event_type"] for e in hit))

ign = [s for s in raw["ignore_segments"]
       if not (float(s["end_time_sec"]) < 6380 or float(s["start_time_sec"]) > 6550)]
print("ignore_overlapping", ign)

before = [r for r in rows if r["t"] <= SHOT_MIN]
after = [r for r in rows if r["t"] >= NET]
print("nearest_before", before[-1] if before else None)
print("nearest_after", after[0] if after else None)
print("VERDICT_EXPECTED INSUFFICIENT_EVIDENCE")
print("FIRST_LIVE_VERIFIED false")
PY

echo "Full prior audit JSON (if present): $OUT/expB_live_sequence_audit.json"
echo "Repo report: docs/V3A_EXPB_B_LIVE_SEQUENCE_SUMMARY.md"
git rev-parse --short HEAD
git status --short
