# Story VA V2 — Strip-Guided Round 2.3 Report

## Verdict

Round 2.3 delivers a **full-match comeback story candidate** (not a four-goal montage): five video-verified score transitions, live DeepSeek-selected non-goal strip contexts, temporal/narrative global relations (no score-order causal claims), and internal clean/QC MP4s with `render_ready=false`.

Primary artifacts:

`/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_3_20261029_181050_fixed/`

Supporting runs:

- Live DeepSeek planner (strips): `.../croatia_r2_3_20261029_181050/`
- Fifth-goal VLM cache source: `.../croatia_r2_3_20261029_165512/verify_event_000153/`

## Score coverage & video evidence

| Transition | Key event | Goal result (media_sec) | Status |
|---|---|---|---|
| →0:1 | `ke_1_…mg_initial_deficit_0` | 982.063 | verified (R2.2 cache) |
| 0:1→1:1 | `ke_2_…mg_trans_1` | 3107.72 | verified (R2.2 cache) |
| 1:1→2:1 | `ke_3_…mg_trans_2` | 3566.64 | verified (R2.2 cache) |
| 2:1→3:1 | `ke_4_…mg_trans_3` | 6461.08 | verified (R2.2 cache) |
| 3:1→4:1 | `ke_5_…event_000153` | 7748.1 | verified (R2.3 targeted; cached VLM + post-shot frame bind) |

All five score anchors are `covered_by_verified_goal=true`. No V1 times / gold causal / `strip_gold`.

`event_000153` was not accepted from `events.json` alone. Qwen coarse/dense windows observed shot + net; result time uses a **real sampled PTS after the shot** (`pair_basis=dense_window_post_shot_frame`).

## DeepSeek non-goal strip selections

Live DeepSeek planner (`181050`): **15 HTTP planner calls**, mode log almost all `llm`. It selected narrative strips first; because it finished without `ke_*` nodes, `ensure_verified_goals_selected` post-step attached the five verified goals and spine relations (no new LLM cost). Goal-endpoint strips `clip27` / `clip59` were excluded as redundant with verified goals.

Retained DeepSeek strips (8) and abbreviated why:

| Strip | Why (DeepSeek) |
|---|---|
| `strip_clip24` | Pre-equalizer buildup / sustained pressure |
| `strip_clip45` | Pre-3-1 pass→foul setup |
| `strip_clip46` | Outcome strip preceding 3-1 |
| `strip_clip58` | Quick restart / pressure before 4-1 |
| `strip_clip31` | Danger between 2-1 and 3-1 |
| `strip_clip50` | Post-bar danger after 3-1 |
| `strip_clip44` | Shot-save danger before later lead |
| `strip_clip49` | Post-bar shot danger after 3-1 |

Excluded by ensure (redundant with verified goals): `strip_clip27`, `strip_clip59`.

## Role of 8.31 predicted strips

Local strip nodes remain `predicted` unless separately video-checked. Planner uses them as narrative context near verified goals. Global graph does **not** upgrade strip-internal algo causality to evidence-backed global `causal`.

## Is the story only goal concatenation?

No. Final EDL: **5 goals + 8 non-goal strips + title cards** (15 segments), chronological playable order with deficit/buildup/turning/climax/resolution beats. Boundary checks: no temporal overlaps in the fixed candidate.

## Global relations with support

| Type | Edge | Support |
|---|---|---|
| temporal ×4 | consecutive verified goals | media times |
| narrative | opening deficit → final 4:1 | score path + verified goals (**not** causal) |

No automatic adjacent-strip narrative fan-out; no score-order `causal` edges.

## vs Round 2.2

| | R2.2 | R2.3 |
|---|---|---|
| Verified goals | 4 | 5 (+3:1→4:1) |
| Story scope | goal-centric T01 | full-match inventory + global planner |
| Non-goal context | limited | 8 live DeepSeek strips |
| Relations | mostly goal temporal | + comeback narrative spine |
| Deliverables | unified strip B + 4-goal EDL | full graph/beats/relations/EDL/clean+QC |

## API / cost (estimates)

| Phase | Calls | Est. USD |
|---|---|---|
| Qwen verify `event_000153` (cached once) | 4 vision | ~0.011 |
| Live DeepSeek planner `181050` | 15 HTTP | ~0.0092 |
| Fixed rebuild (ensure goals + render) | 0 new LLM/VLM | 0 |

Sandbox note: Cursor default network allowlist blocked `llmapi.paratera.com` until workspace `/data2/lpy1/.cursor/sandbox.json` allowed `*.paratera.com`.

## Still unverified / limitations

- Selected strips remain predicted (not frame-verified actions).
- DeepSeek initially omitted `ke_*`; ensure-step repairs that (documented in planner trace).
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
11. Git commit SHA: `a0bde048a64136878486491940ea9b67b0539d17`

## Forbidden inputs (honored)

No gold causal JSON, no `strip_gold`, no V1 goal times / story results for timing or fill-in, no 8.31 production retune, no Croatia-hardcoded story times in planner logic.
