# Stage6 B: OCR-optional source-video broadcast audit

Branch `story-va-v3a-stage6-video-broadcast-verifier`.

This is a **video-first evidence retrieval stage**, NOT a complete
FIRST_LIVE classifier. It reuses Stage3's real Qwen shot/net times via
the Stage4 queue, verifies original MP4 SHA, and scans earlier original
broadcast frames using 64-bit DCT perceptual hashes. No OCR, Gold,
P14, human goal timestamps, new paid HTTP, or EDL edits.

## Execute on server

```bash
cd 10.27scasual_chain
PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_stage6_broadcast_verifier.py \
  tests/test_v3a_stage5_broadcast_temporal_audit.py \
  tests/test_v3a_goal_video_repair.py

STAGE4=/tmp/lpy1_v3a_stage4_B_first_live_review_fullctx_20261113/first_live_review_queue.json
B=/tmp/lpy1_v3a_blind_repair_B_historical_20261112
Q="$B/agent_run_goal_video_stage2_v1/02_round_01/source_goal_video_review/source_goal_video_review_queue.json"
test -s "$STAGE4" && test -s "$Q" || exit 2
SOURCE=$(python - "$Q" <<'PY'
import json,sys
print(json.load(open(sys.argv[1],encoding="utf-8"))["source_video"])
PY
)
test -s "$SOURCE" || exit 2
OUT=/tmp/lpy1_v3a_stage6_B_video_first_20261113
test ! -e "$OUT" || { echo "Refusing overwrite"; exit 2; }
PYTHONPATH=algo python -m story_video_agent_v3.stage6_broadcast_verifier \
  --source-mp4 "$SOURCE" --stage4-queue "$STAGE4" \
  --out-dir "$OUT" --scan-step-sec 1 \
  --earlier-lookback-sec 180
```

Inspect `$OUT/video_broadcast_audit.json`: scanned PTS coverage,
number and distance of earlier visually similar frames, and any decoding
failures. No match is **not** first-live proof. Matches may be ordinary
football pitch similarities; manually audit candidates as algorithm
development diagnostics, not as a production human-dependent gate.

## Follow-up engineering

Build a **general broadcast phase recognizer** (live/replay/slowmo/unknown)
from temporally adjacent original frames and shot-boundary dynamics, then
combine it with **same-action retrieval** across the complete relevant
earlier source interval. The present pHash is only a cheap diagnostic
baseline and cannot establish action identity. Test against replay and
same-pitch hard negatives across different matches before permitting
`FIRST_LIVE_VERIFIED`. OCR remains optional auxiliary evidence.

Do not unlock EDL, do not claim autonomous first-live verified, and do not
run new paid VLM calls without authorization.
