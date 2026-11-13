# V3-A Stage5: independent original-video temporal audit (B raw-only)

**Zero HTTP, zero new model calls, no EDL modification.** Work from branch
`story-va-v3a-stage5-broadcast-temporal-audit`.

## Why Stage4 B was UNKNOWN

The first-broadcast module only certifies FIRST_LIVE with an independently
evidenced review. Absence of a raw event inside the goal interval is NOT
evidence of first broadcast. Stage3 Qwen3.6/3.7 both claim live shot/net,
but their sparse samples cannot rule out replay or slow motion.

Stage4 also exposed a **real clip coverage bug**: the requested context
[6428.62, 6477.62] was silently truncated to [6428.62, 6468.62] by a
40-second cap. This branch raises the bounded context extraction to 60s,
records requested vs actual coverage, and adds `continuous_context_complete`.
Do not reuse the old 40s clip as if it covered the full requested context.

## First run: zero-paid tests and source OCR

```bash
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_stage5_broadcast_temporal_audit.py \
  tests/test_v3a_goal_video_repair.py \
  tests/test_v3a_stage3_goal_video_rounds.py

B=/tmp/lpy1_v3a_blind_repair_B_historical_20261112
STAGE4=/tmp/lpy1_v3a_stage4_B_first_live_review_20261113/first_live_review_queue.json
Q="$B/agent_run_goal_video_stage2_v1/02_round_01/source_goal_video_review/source_goal_video_review_queue.json"
test -s "$STAGE4" && test -s "$Q" || exit 2
mapfile -t INPUTS < <(python - "$Q" <<'PY'
import json,sys
q=json.load(open(sys.argv[1],encoding="utf-8"))
print(q["source_video"])
print(q["events_path"])
PY
)
test -s "${INPUTS[0]}" && test -s "${INPUTS[1]}" || exit 2
OUT=/tmp/lpy1_v3a_stage5_B_temporal_audit_20261113
test ! -e "$OUT" || { echo "Do not overwrite"; exit 2; }

PYTHONPATH=algo python -m story_video_agent_v3.stage5_broadcast_temporal_audit \
  --source-mp4 "${INPUTS[0]}" --events-json "${INPUTS[1]}" \
  --stage4-queue "$STAGE4" --out-dir "$OUT" --step-sec 2
```

Review `$OUT/broadcast_temporal_audit.json`:
- source SHA, two independent model shot/net PTS spreads;
- OCR score observations (frame paths and PTS), strong vs weak readings;
- whether two strong **pre-shot 0:1** and two strong **post-net 1:1** observations
  exist, plus conflicting early 1:1 or late 0:1;
- raw event replay overlap (absence of event is NOT a negative proof);
- `ready_for_broadcast_review` versus `first_live_verified=false`.

The source video is the **original MP4**. No P14, corrected EDL, Gold, or
manually supplied goal timestamp may enter. Shot/net are obtained only from
the existing real Qwen model observation logs.

## Fix and regenerate full broadcast context (zero-paid)

Rerun Stage4 in a **new** output directory using the same original source
and Stage3 Qwen logs (see Stage4 runbook for `--semantic-log` paths).
The fixed `first_live_window_evidence` should now produce a full
49-second continuous context clip, not 40 seconds. Assert:
- `context_truncated=false`
- `continuous_context_complete=true`
- actual `clip.media_out >= context_window.end - 0.05`.

If any of these fails, **do not** use the clip for first-broadcast review.

## Next decision

If original-source OCR independently corroborates 0:1 → 1:1 after shot/net,
and the full context clip is available, advance to an independently evidenced
**broadcast-phase** check: continuous live play vs replay transition,
slow-motion/camera changes, and whether an earlier original broadcast
contains the same goal action. This must be a separately auditable observation,
not an LLM's bare `live=true` claim. Only then build an authenticated
SHA+PTS first-live review, attempt guarded EDL repair and render a video.

If OCR is weak or inconsistent, report `SCORE_TRANSITION_INSUFFICIENT_OCR`
or conflict and stop; do not manufacture a score transition from the two
VLM model claims. `FIRST_LIVE_VERIFIED=false`, `EDL_REPAIRED=false`
remain unchanged in this stage.

After B reaches an actual rendered-candidate test, repeat A with the same
general mechanism and rerun C negative control. The ultimate user-facing
metric is story-video quality, not a green gate alone.
