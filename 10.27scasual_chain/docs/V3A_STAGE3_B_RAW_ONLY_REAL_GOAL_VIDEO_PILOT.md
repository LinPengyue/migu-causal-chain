# V3-A Stage3: raw-only B source VIDEO semantic pilot

**Status: pilot commands prepared, no server execution or paid API call yet.**
Base evidence: Stage2 server report `5bcd840`; this branch fixes the reused
P13 video's dense second-round trigger and complete-evidence ranking. A/B/C
remain unchanged and their original source/score files MUST be preserved.

## Why this exact pilot first

Stage2 B (historical P12, RAW_EVENTS_ONLY, 749 raw events, zero annotated Goal)
detected score transition 0:1→1:1 from source scoreboard states and extracted
two continuous original-source candidate videos:
- `score_unknown_core`: [6402.07, 6437.07]
- `uncovered_gap_tail`: [6440.62, 6465.62]

These are **search output**, NOT goal/action oracle timestamps. A has an extra
Goal-atom-derived window unavailable to B; therefore **test B first** to
avoid accidental DEV annotation dependence. The selected B window is the
*latest existing non-replay candidate* per Stage2 queue — a generic retrieval
heuristic, not a label or reference EDL. Its video contents have NOT been
verified yet.

Original `run_remote_vlm_verification` would skip round 2 whenever round 1
claimed `observed_net=true`, even when `observed_shot=false`. That can
prematurely stop before the action is observed. Fixed:
1. Round 2 is skipped only when one round has cited shot AND cited net, live
   claim, attacking-side match, continuous-live claim, and no uncertainty.
2. The best round is chosen by **complete cited evidence**, not net alone.
3. Partial observations in separate VLM calls are NEVER merged to construct
   an artificial continuous shot→net claim.
4. This is a source-video *observation* test; no first-LIVE gate opens and no
   EDL is modified. An 8–12-frame sample is NOT native full video ingestion.

## Step 0: zero-HTTP regression + config

In a NEW worktree at `origin/story-va-v3a-stage3-adaptive-video-verify`:

```bash
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_stage3_goal_video_rounds.py \
  tests/test_v3a_goal_video_repair.py \
  tests/test_v3a_goal_coverage_critic.py \
  tests/test_v3a_blind_goal_repair_challenge.py

B=/tmp/lpy1_v3a_blind_repair_B_historical_20261112
Q="$B/agent_run_goal_video_stage2_v1/02_round_01/source_goal_video_review/source_goal_video_review_queue.json"
test -s "$Q" || exit 2

# Choose a candidate ONLY from Stage2 B's recorded search queue.
# Do not read any corrected EDL, private_eval, P14 or Gold.
mapfile -t INFO < <(python - "$Q" <<'PY'
import json, sys
q=json.load(open(sys.argv[1],encoding="utf-8"))
issues=[x for x in q.get("issues",[]) if x.get("status")=="SOURCE_CLIPS_READY_UNVERIFIED"]
assert len(issues)==1, "expected one independently detected issue"
i=issues[0]
candidates=[c for c in i.get("continuous_candidate_clips",[])
            if c.get("clip_path") and c.get("semantic_label") not in ("replay","wrong_attacking_side")]
assert candidates, "no candidate videos"
c=max(candidates,key=lambda x: float(x["media_in"]))
print(q["source_video"])
print(c["clip_path"])
print(c["media_in"])
print(c["media_out"])
print(i["issue_id"])
print(",".join(map(str,i["score_before"])))
print(",".join(map(str,i["score_after"])))
PY
)
SRC=${INFO[0]}; CLIP=${INFO[1]}; START=${INFO[2]}
END=${INFO[3]}; ISSUE=${INFO[4]}
BEFORE=${INFO[5]}; AFTER=${INFO[6]}
test -s "$SRC" && test -s "$CLIP" || exit 2
BOUNDS="$B/agent_run_goal_video_stage2_v1/02_round_01/source_goal_video_review/$ISSUE/score_bounds.json"
test -s "$BOUNDS" || exit 2

# 0 HTTP; check requested model, availability, cap and request compatibility.
PYTHONPATH=algo python -m story_video_agent_v3.vlm_verify_cli \
  --video "$SRC" --media-in "$START" --media-out "$END" \
  --role "$ISSUE" --score-before "$BEFORE" --score-after "$AFTER" \
  --out-dir /tmp/lpy1_v3a_stage3_B_config_audit_20261113 \
  --max-calls 2 --max-cost-usd 0.10 --max-completion-tokens 2048 \
  --config-audit-only
```

Inspect config audit: model, provider, `ready_for_real_when_approved`,
effective vision token limit, global budget caps. No service password/key
should appear in reports. STOP if provider not ready.

## Step 1: ONLY with explicit authorization for this paid trial

The following command can make at most two model requests and is capped at
**$0.10** by the existing provider; the cap is an upper bound, not a quoted
actual bill. It is an observational experiment, not a production run.

```bash
# Requires explicit approval and working provider credentials.
OUT=/tmp/lpy1_v3a_stage3_B_real_video_20261113
test ! -e "$OUT" || { echo "Refuse overwrite of existing trial"; exit 2; }

PYTHONPATH=algo python -m story_video_agent_v3.vlm_verify_cli \
  --video "$SRC" --media-in "$START" --media-out "$END" \
  --continuous-clip "$CLIP" \
  --role "$ISSUE" --score-before "$BEFORE" --score-after "$AFTER" \
  --score-bounds-json "$BOUNDS" \
  --attacking-team-hint "The side whose score increases across the supplied score transition; do not assume a team name or jersey from metadata" \
  --out-dir "$OUT" \
  --max-calls 2 --max-cost-usd 0.10 --max-completion-tokens 2048 \
  --enable-real-api --i-approve-budget
```

Do not pass `--allow-auto-verify`, do not change `observation_only=True`,
and do not add a target goal timestamp or corrected P14 action cut to any
model prompt/input. Do NOT rerun automatically if model returns unresolved.

## What to report, in order

From `$OUT/rounds_full.json`, `round1_frames.json`,
`round2_frames.json`, `vlm_verify_summary.json`,
`automated_semantic_log.json` and `api_provider_status.json`:
1. Actual provider, call attempts, tokens/cost estimate, failures.
2. Round1 and Round2 claims separately: shot/net/team/phase, cited frame
   IDs and original source PTS, plus whether images were actually sent.
3. Whether second round was used when first was net-only or shot-only.
4. `structurally_ready_for_automated_verify` and each
   `crosscheck.evidence_gaps`. Report exactly which proof is missing.
5. Verdict **SOURCE_VIDEO_SEMANTIC_CONFIRMED / INCOMPLETE / REPLAY / UNCHECKABLE**.
   The CLI's legacy `possible_first_live` is NOT authoritative proof.
6. `FIRST_LIVE_VERIFIED=false`, `EDL_REPAIRED=false` and
   `STORY_IMPROVED=UNVERIFIED` until separate continuous broadcast review,
   evidence binding and actual story re-render succeed.

This is a **single historical known-match development trial**, not
cross-match unseen generalization. The first phase's purpose is to resolve
whether source-video semantics can actually recognize a missed goal WITHOUT
Goal annotation. Do not add another localization/OCR module if it cannot.

## Next only if source shot+net are grounded

Reuse the source-evidence and broadcast-timeline verifier to check original
FIRST LIVE rather than replay/slow-motion, then bind the verified source
PTS/shot/net and invoke the existing guarded goal-EDL insert, renderer,
fullcut Verifier and blinded A/B video review. For an independently video
reviewed human file, mark HUMAN_ASSISTED rather than autonomous.

Do not claim `EDL_REPAIRED=true` merely because a sampled-frame model wrote
`observed_net=true`, or because a candidate time interval overlaps a
private reference goal. A candidate EDL and a promoted final EDL are separate.
