# Story VA V2 — Strip-Guided Round 2.3 Report

## Verdict

Round 2.3 upgrades the Croatia–Canada candidate from a **four-goal score montage** to a **full-match comeback story**: five video-verified score transitions, seven DeepSeek-selected non-goal strip contexts, global temporal/narrative relations (no score-order causal claims), and internal clean/QC candidate MP4s with `render_ready=false`.

Primary artifacts:

`/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_3_20261029_174500_composed/`

## Score coverage & video evidence

| Transition | Key event | Goal result (media_sec) | Status |
|---|---|---|---|
| →0:1 | `ke_1_…mg_initial_deficit_0` | 982.063 | verified (R2.2 cache) |
| 0:1→1:1 | `ke_2_…mg_trans_1` | 3107.72 | verified (R2.2 cache) |
| 1:1→2:1 | `ke_3_…mg_trans_2` | 3566.64 | verified (R2.2 cache) |
| 2:1→3:1 | `ke_4_…mg_trans_3` | 6461.08 | verified (R2.2 cache) |
| 3:1→4:1 | `ke_5_…event_000153` | 7748.1 | verified (R2.3 targeted; cached VLM + post-shot frame bind) |

All five score anchors in `full_match_key_events.json` are `covered_by_verified_goal=true`. No V1 times / gold causal / `strip_gold` were used.

`event_000153` was **not** treated as verified from `events.json` alone. Qwen windows (strip/goal coarse+dense) observed shot + net language; final result time uses a **real sampled PTS after the shot** in the dense window (`pair_basis=dense_window_post_shot_frame`), not observation midpoint and not V1 labels.

## DeepSeek non-goal strip selections

Authentic DeepSeek planner run: `croatia_r2_3_20261029_165512` (12 HTTP planner calls). Later rebuilds hit **proxy 403**, so the composed delivery **reuses those select/exclude reasons** and adds the fifth verified goal.

Selected strips (with DeepSeek why, abbreviated):

| Strip | Role in story |
|---|---|
| `strip_clip24` | Pre-equalizer buildup |
| `strip_clip25` | Post-equalizer momentum / pressure |
| `strip_clip27` | Throw-in buildup toward 2-1 |
| `strip_clip31` | Danger after 2-1 (tackle→corner) |
| `strip_clip44` | Danger before 3-1 |
| `strip_clip45` | Pre-3-1 pass→foul setup |
| `strip_clip46` | Outcome strip preceding 3-1 |

These are **not** the full 63 predicted chains sorted by time. Exclusion reasons remain in `story_candidates.json` / planner trace.

## Role of 8.31 predicted strips

- Local strip nodes stay `verification_status=predicted` unless separately video-checked.
- Planner uses strip summaries as **candidate narrative context** (danger/outcome near verified goals).
- Global graph links strips to beats/clips; local causal sequence inside a strip is algorithm prediction, not upgraded to evidence-backed global `causal`.

## Is the story only goal concatenation?

No. Candidate EDL has **7 non-goal strip segments + 5 goals + title cards** (14 segments). Chronological playable order mixes deficit-period / mid-comeback pressure strips between goals. QC notes one **5.0s temporal overlap** between equalizer goal and `strip_clip25` (flagged in `boundary_checks`).

## Global relations with support

| Type | Edge | Support |
|---|---|---|
| temporal | consecutive verified goals | media times |
| narrative | opening deficit → final 4:1 | score path + verified goals (explicitly **not** causal) |
| narrative | `strip_clip27` → equalizer | DeepSeek/rule narrative; strip predicted |

No automatic adjacent-strip narrative fan-out; no score-order `causal` edges.

## vs Round 2.2

| | R2.2 | R2.3 |
|---|---|---|
| Verified goals | 4 | 5 (adds 3:1→4:1) |
| Story scope | T01 beats around four goals | Full-match key inventory + global planner |
| Non-goal context | limited / goal-centric EDL | 7 DeepSeek-selected strips |
| Relations | mostly goal temporal/narrative | + strip→goal narrative; fifth-goal temporal |
| Deliverables | unified strip B + 4-goal candidates | full graph/beats/relations/EDL/clean+QC |

## API / cost (estimates)

| Phase | Calls | Est. USD |
|---|---|---|
| DeepSeek planner (165512) | 12 HTTP | ~0.0073 |
| Qwen verify `event_000153` | 4 vision | ~0.0110 |
| Composed rebuild | 0 new LLM/VLM | 0 (cache reuse) |

Proxy 403 blocked fresh DeepSeek during later runs; vision for the fifth goal was paid once and reused via `--reuse-verify-cache` / offline finalize.

## Still unverified / limitations

- Selected **strip chains** remain predicted; only goals are `verified_action`.
- DeepSeek could not be re-queried after proxy failure; strip choices are from the successful prior planner trace.
- One equalizer / post-goal strip overlap remains in candidate EDL.
- `render_ready=false`; internal candidates only.
- V1 freeze and independent `8.31causal_chain` production params untouched.

## Deliverables checklist

1. `full_match_key_events.json`
2. `story_planner_trace.json`
3. `story_candidates.json`
4. `story_graph.json`
5. `story_beats.json`
6. `story_relations.json`
7. `candidate_edl.json`
8. `story_clean_candidate.mp4`
9. `story_qc_candidate.mp4`
10. this report
11. Git commit SHA: `5fc1a9e66e9a292df2c904e19d245a949e87295a`

## Forbidden inputs (honored)

No gold causal JSON, no `strip_gold`, no V1 goal times / story results for timing or fill-in, no 8.31 production retune, no Croatia-hardcoded story times in planner logic.
