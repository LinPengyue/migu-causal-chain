# Stage7 — B source video temporal broadcast diagnostics

Branch: `story-va-v3a-stage7-temporal-broadcast`.

This is **not yet an autonomous first-live verifier**. It measures temporal
cut candidates around the observed goal on original video, independent of
OCR. It cannot certify replay/live from cuts alone, and cannot repair EDL.

```bash
cd 10.27scasual_chain
PYTHONPATH=algo python -m pytest -q tests/test_v3a_stage6_broadcast_verifier.py tests/test_v3a_stage5_broadcast_temporal_audit.py
B=/tmp/lpy1_v3a_blind_repair_B_historical_20261112
Q="$B/agent_run_goal_video_stage2_v1/02_round_01/source_goal_video_review/source_goal_video_review_queue.json"
STAGE4=/tmp/lpy1_v3a_stage4_B_first_live_review_fullctx_20261113/first_live_review_queue.json
test -s "$Q" && test -s "$STAGE4" || exit 2
SOURCE=$(python - "$Q" <<'PY'
import json,sys
print(json.load(open(sys.argv[1],encoding="utf-8"))["source_video"])
PY
)
OUT=/tmp/lpy1_v3a_stage7_B_temporal_20261113
test ! -e "$OUT" || exit 2
PYTHONPATH=algo python -m story_video_agent_v3.stage7_temporal_broadcast \
  --source-mp4 "$SOURCE" --stage4-queue "$STAGE4" \
  --out-dir "$OUT" --step-sec 0.5
```

Inspect `$OUT/temporal_broadcast_diagnostics.json`: decoded coverage,
temporal cut candidate PTS relative to shot/net, and histogram/pixel changes.

**Next required engineering, not yet done**: implement segment-level same-action
retrieval (temporal alignment, not independent pHash hits), independently
verified broadcast phase labels (live/replay/slow motion/unknown), hard negative
controls (different shot same pitch; alternate camera; replay at normal speed),
and test on A and held-out matches. No Gold/P14, no paid HTTP without approval.

Gate stays FIRST_LIVE=false, EDL unchanged. Do not claim Stage7 diagnostic
output is a completed automatic first-broadcast classifier.
