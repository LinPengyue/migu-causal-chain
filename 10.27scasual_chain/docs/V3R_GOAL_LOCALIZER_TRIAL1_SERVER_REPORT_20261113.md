# V3-R Goal Localizer Trial 1/2 — server report

Branch: `story-va-v3r-goal-localizer-trial1-20261113` @ `fc61d17`  
Code SHA: `fc61d172d35fd0b0e64f066666a672f46ab625ee`  
Source MP4 SHA: `a66147f79609c8fbf831a8bd29de4c6d7f746b314b2b18a88ffb1fc5f319da9c`  
Events SHA: `ddae99b21cbfcd1c75ddf620d957578e57c2c013d607ac893655c4d52b7e779e`  
Out: `/tmp/lpy1_v3r_goal_localizer_trial1_20261113/`  
Paid HTTP: **0**. No recovery JSON rewrite. No EDL/BEST/P14 changes.

## Command (as documented)

```bash
PYTHONPATH=.:algo python -m story_video_agent_v3.first_live_localize \
  --source-mp4 "$MP4" --events-json "$EVENTS" \
  --goal-recovery "$REC" --out-dir "$OUT" \
  --candidate-id goalcand_03_01_to_11 \
  --max-candidates 4 --max-video-read-sec 90 \
  --expected-source-sha256 a66147f7… --expected-events-sha256 ddae99b2…
```

Exit **0**. Localizer bucket string: `not_found_in_budget` (machine).  
**Human audit verdict: `CANDIDATE_FOUND_UNVERIFIED`** — not PASS, not recovered.

## What the localizer proposed

Score bracket from recovery: `6410.07–6535.62` (board lag; not action).  
OCR narrowed unknown interval to `6410.07–6460.62` (`first_after` OCR @ 6460.62 = 1:1).  
Search plan window: `6395.07–6465.62`. Planned read 80s / budget 90s.

| # | origin | PTS | Decoded | Covers prior human shot/net refs (~6447.88 / ~6450.6)? |
| --- | --- | --- | --- | --- |
| 1 | `score_unknown_core` | 6402.07–6437.07 | yes | **no** (ends before action) |
| 2 | `uncovered_gap_tail` | **6440.62–6465.62** | yes | **yes** |
| 3 | `uncovered_gap_head` | 6395.07–6415.07 | yes | no |

3 continuous accurate clips extracted. No auto `goal_action_sec`. No EDL insert.

## Visual check of the covering clip (sparse frames)

Clip: `.../uncovered_gap_tail_6440_continuous_accurate.mp4`

| Sparse PTS | Clock / score (readable) | Content |
| --- | --- | --- |
| 6441.62 | 75:48 / 0–1 | live wide play (pre-action) |
| 6453.12 | 76:00 / board still shows 0–1 | motion-blur midfield (post-net, board lag) |
| 6464.12 | 76:11 / **1–1** | sideline huddle / celebration |

So the **action window is inside the candidate set**, but sparse samples skip the exact shot/net instants; offline classifier left `observed_shot=false`, `observed_net=false`, `live_or_replay=unknown`. Dense frames (24) exist but were not auto-verified as shot/net.

Evidence pack top row incorrectly preferred head gap `6395–6415` (no action). All three candidates: `semantic_label=unresolved`, `goal_action_verified_ok=false`.

## Stage-specific diagnosis

| Stage | Finding |
| --- | --- |
| Candidate recall | **Hit** — gap_tail covers the equalizer action PTS |
| OCR / score bracket | Usable constraint; `score_unknown_core` window alone would **miss** the action |
| Frame coverage | Continuous clip OK; sparse cites miss shot/net peak |
| Semantics (offline) | **Fail closed** — insufficient_signals; no VLM this trial |
| First-live proof | **Absent** — not FIRST_LIVE_VERIFIED; extraction ≠ verification |
| Consume path | Existing `goal_recovery.apply_action_overlays` / verified observation interface would need `goal_action_verified_ok` + independent first-live; **still missing** |

## Trial-2 decision

**No Trial-2 recall patch warranted** from this run: search did not miss the action.  
Remaining gap is **semantic + first-live evidence**, not a general missed-coverage bug suitable for one cross-match-safe localizer tweak.

Per protocol: **do not auto-insert**; do not add gates/modules here.  
For story-quality progress without reliable raw-only recovery: **return to P14 atomic-enriched development track** (P14 / BEST untouched this run).

## Artifacts

- Docs mirror: `docs/v3r_goal_localizer_trial1_20261113/`
- Full clips/frames remain under `/tmp/lpy1_v3r_goal_localizer_trial1_20261113/` (not committed)
