# Stage4: B raw-only FIRST LIVE review (zero HTTP)

Stage3 `acb3194`: real Qwen3.6 and Qwen3.7 independently cite shot/net
in the Stage2 B `uncovered_gap_tail` candidate. Both are observation-only.
This stage verifies whether the SAME source-video action is its first
broadcast occurrence. It does NOT infer FIRST_LIVE from the VLM live label.

Branch: `story-va-v3a-stage4-first-live-review`.
No Gold, P14 EDL, or human Goal annotations may enter this stage.

## Execute on original server (zero HTTP)

```bash
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3
B=/tmp/lpy1_v3a_blind_repair_B_historical_20261112
Q="$B/agent_run_goal_video_stage2_v1/02_round_01/source_goal_video_review/source_goal_video_review_queue.json"
test -s "$Q" || exit 2

# The two observation logs must be the actual saved Stage3 server outputs.
# Adjust paths to the server's original directories, not GitHub preview copies.
Q36=/path/to/actual/qwen36/automated_semantic_log.json
Q37=/path/to/actual/qwen37/automated_semantic_log.json
test -s "$Q36" && test -s "$Q37" || exit 2

mapfile -t SRC < <(python - "$Q" <<'PY'
import json,sys
q=json.load(open(sys.argv[1],encoding="utf-8"))
print(q["source_video"])
print(q["events_path"])
PY
)
test -s "${SRC[0]}" && test -s "${SRC[1]}" || exit 2
OUT=/tmp/lpy1_v3a_stage4_B_first_live_review_20261113
test ! -e "$OUT" || { echo "Refuse overwrite"; exit 2; }

PYTHONPATH=algo python -m story_video_agent_v3.stage4_first_live_review \
  --source-mp4 "${SRC[0]}" --events-json "${SRC[1]}" \
  --stage2-queue "$Q" \
  --semantic-log "$Q36" --semantic-log "$Q37" \
  --out-dir "$OUT" --context-pad-sec 12
```

Inspect:
- `$OUT/first_live_review_queue.json`
- `$OUT/broadcast_context/broadcast_timeline_review.json`
- `$OUT/broadcast_context/context_clip.mp4` (original continuous broadcast)

Required review: actual broadcast phase across shot→net, whether the same
goal action occurs earlier in the original timeline, any replay transition
graphics, changed camera angle or slow-motion, and whether continuous context
matches model-cited shot/net frames. Raw event `is_replay=false` and VLM
`live` claims are NOT enough. Any missing evidence remains UNKNOWN.

If independent review confirms first broadcast, prepare a separate source-SHA
and PTS-bound review with auditable frame/clip hashes. Only then attempt
`repair_goal_coverage_from_video_reviews`, candidate render, original
Verifier, and compare actual final cut. Human review must be labeled
HUMAN_ASSISTED, never autonomous. Do not manually set FIRST_LIVE_VERIFIED
inside the review JSON to force an EDL insert.

Then repeat the same path on A, and rerun C negative control. The final
success criterion is **correct final EDL + rendered MP4 + preserved narrative
quality**, not merely a model's goal claim.
