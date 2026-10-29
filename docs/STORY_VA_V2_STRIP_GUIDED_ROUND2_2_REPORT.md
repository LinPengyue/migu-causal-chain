# Story Video Agent V2 — Strip-Guided Round 2.2

**Branch:** `story-va-video-driven`  
**Baseline strip A:** frozen production causal_chain6 on plain events (**62** chains)  
**V1 / standalone 8.31 / production params:** frozen  
**render_ready:** `false`

## Scope

Finish Croatia key-goal recovery and move from single-candidate experiments to a **unified full-match** enhanced timeline → strip A/B → T01 Story Graph → candidate EDL.

## Task 1 — `mg_initial_deficit_0` video recovery

| Item | Result |
|--|--|
| Candidate | First scoreboard non-zero `→ [0,1]` @ confirm 1079.06s |
| Raw emit (pre-audit) | shot/result ≈ **1026–1027s** (replay window) |
| Live/replay audit | **corrected_live_rebind** — live net cite `f_0059_982050` @ **982.063s** |
| Method | Rebind from existing verification text; **no extra VLM call** after recovery |
| Live status | `broadcast_phase=LIVE` |

Artifact: `croatia_r2_2_20261029_161952/mg_initial_deficit_0/` (+ audit in unified merge).

## Task 2 — Merge verified Goals (no re-pay for mg_trans_*)

| Goal | Score | shot → result | Audit | Source |
|--|--|--|--|--|
| `mg_initial_deficit_0` | →0:1 | 982.063 → 982.063 | corrected_live_rebind | R2.2 recovery + audit |
| `mg_trans_1` | 0:1→1:1 | 3105.08 → 3107.72 | ok | cached R2.1 |
| `mg_trans_2` | 1:1→2:1 | 3562.32 → 3566.64 | ok | cached R2.1 |
| `mg_trans_3` | 2:1→3:1 | 6457.1 → 6461.08 | ok | cached R2.1 |

- Deduped by score transition; all four `verification_status=verified_action`.
- `mg_trans_*` marked `reused_no_new_vlm=true`.
- Evidence inventory + merge audit written.

## Task 3 — Unified Strip A/B (not sum of single runs)

| | A (plain) | B (unified enhanced) |
|--|--|--|
| Chains | **62** | **63** |
| outcome/goal endpoints | 1 | **4** |
| only_in_B (sample) | — | 7 new/changed chain keys |

Single production reinfer on merged enhanced events. No margin retune.

## Task 4 — Story Nodes

Four video-verified Goal nodes retained as **independent key nodes** even when strip template ≠ pure outcome (e.g. equalizer on `throw_in_build_up_chain`). No invented local causal links.

## Task 5 — T01 Story Beats / Graph

- `discovery_status`: **story_candidate** (deficit→lead score path)
- Score path (board anchors): `[0,1] → [1,1] → [2,1] → [3,1] → [4,1]`
- Relations: **temporal** along verified goal times; **narrative** deficit→lead; **causal** not emitted from score order
- Beats: setup / buildup / turning / climax / resolution mapped to goal nodes

## Task 6 — Live/replay splice check

| Check | Policy |
|--|--|
| Replay shot + live net | rejected / rebind |
| Result after score confirm | flagged |
| Shot–result gap > 20s | rejected at merge |
| Deficit case | replay 1027s → live **982.063s** |

## Task 7 — Candidate EDL

| Segments | 4 (one per verified goal) |
| Boundary conflicts | none |
| Narrative completeness | ok (opening_deficit + later goals) |
| Gates | independent_review / delivery / **render_ready = false** |
| Internal review clips | 4 short mp4 under `review_pack/clips/` |

## Deliverables (unified run)

Root: `_story_va_outputs/v2/strip_guided/croatia_r2_2_20261029_162833_unified/`

| Artifact | Path |
|--|--|
| Enhanced events | `enhanced/enhanced_events_for_strip.json` |
| Strip A/B | `strip_ab/strip_A_original.json`, `strip_B_enhanced.json`, `strip_ab_compare.json` |
| Story graph | `story_graph.json`, `story_beats.json`, `story_relations.json` |
| Candidate EDL | `candidate_edl.json` |
| Evidence | `evidence_inventory.json`, `goal_merge_audit.json` |
| Review pack | `review_pack/` |
| CLI report | `cli_report.json` |

## Code

- `v2_strip_guided_r2_2_cli.py` — orchestrator  
- `v2_strip_guided_r2_2_merge.py` — cache merge + dedupe  
- `v2_goal_live_replay_audit.py` — splice audit / live rebind  
- `v2_strip_guided_r2_2_story.py` — T01 graph  
- `v2_strip_guided_r2_2_edl.py` — candidate EDL  
- Tests: `test_v2_strip_guided_r2_2.py`

## Notes / residual risk

1. Opening deficit uses **same-frame** live “goal scored / ball enters net” cite (982.063s); denser live shot/result split was not re-paid after audit correction.  
2. Scoreboard path includes **4:1**; no separate video-verified Goal for that final increment in this round.  
3. Equalizer strip classify remains non-outcome template; node still retained.

## Forbidden (honored)

No gold causal.json, strip_gold, V1 times, or production param changes. Independent 8.31 / V1 untouched.
