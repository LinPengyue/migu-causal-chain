# Story Video Agent V2 — Event-Guided Round 2

**Baseline:** `story-va-video-driven@1427b9f` (+ this commit)  
**V1 freeze:** `462ea11` unchanged  
**render_ready:** `false`  
**Outputs:** `/data2/lpy1/_story_va_outputs/v2/event_guided/round2_croatia/`

## 1. Round 1 offline audit (no overwrite of R1)

Source: `croatia_eg_20261028_182542` → `audit_r1/`

| Finding | Detail |
|--|--|
| R1 `action_recall=0.6` (±90s) | **Invalid as action proof** |
| V1 refs | 4 goal-action + 1 prelude (`lead_extend_1_goal_action_approach`) |
| Strict action Gold | **0** — all V1 goal windows `pipeline_verified=false` → **weak_reference only** |
| Weak-ref strict recall (≤5s / IoU≥0.25) | **0.0** |
| Weak-ref loose (≤45s / IoU≥0.1) | **0.5** (opening ~30s, equalizer ~11s) |
| Go-ahead | Missed (~149s lag) |
| Planner autonomy | Mid-loop was **rule-fixed offsets**; DeepSeek mostly **terminal**; `event_candidates.json` unused |
| Relations | Causal equalizer→go-ahead **without** `supporting_evidence_ids` |
| Keyword grades | Inflated (celebration / midfield marked localized) |

Artifacts: `round2_audit.json`, `action_localization_eval.json`, `v1_reference_split.json`

## 2. Agent redesign

| Change | Purpose |
|--|--|
| `CandidateBoard` + early150/early90 probes | Queryable candidates; Score_Recognition lag |
| DeepSeek mid-loop tools | `list_*`, `select`, `observe_window`, `shift_search`, `reject`, `confirm_localization` |
| Frame-bound evidence | `action_localized` requires shot+net **with frame cites**; keyword-only → not localized |
| Mixed live/replay cutaway | Single “replay angle” after live shot/net no longer blocks localization |
| Relation review | Causal without evidence → downgrade to narrative; no score-order causal fiction |
| Modes | `fixed` / `rule` / `agent` |
| Review packs | Short clips + keyframes under `review_pack/` |

## 3. Targeted go-ahead (real API)

`targeted_goahead_agent2_20261028_191736` (+ offline regrade):

- DeepSeek mid-loop (`llm_mid`×6): observe → shift earlier on lag probes.
- Early probe **3544–3556** shows shot→net with frames; after mixed-replay fix → would be `action_localized`.
- Center error vs weak go-ahead gold: **~27s** (R1 ~173s) → **loose hit**, still not strict.
- Wrong late confirm at ~3689 remains a failure mode (confirm spam / false positive risk).

## 4. Full Croatia A/B/C (`*_20261029_093731`)

| Mode | Weak strict | Weak loose | LLM mid | Cost (est) | Time |
|--|--|--|--|--|--|
| **Event-Fixed** | 0.0 verified* | 0.0 verified* | — | $0 | ~0s |
| **Event-Rule** | **0.0** | **0.5** | 0 | **~$0.027** | ~291s |
| **Event-Agent** | **0.0** | **0.0** | **17** | **~$0.038** | ~644s |

\*Fixed event-time **proximity** (unverified): strict≈0.75 / loose≈1.0 — reported separately as `fixed_event_time_proximity_only`, **not** action localization.

### Event-Rule highlights

- Observe/shift/reject loop fixed (no infinite shift).
- Localized go-ahead probe ~3542 (`action_localized`); lead-extend loose ~7s.
- Opening/equalizer still weak under strict thresholds.

### Event-Agent highlights / failures

- **Autonomy proven:** 17 mid-loop DeepSeek decisions (not terminal-only).
- **No recall gain vs Rule** on this match; loose recall **worse** (−0.5).
- Failure: after 2 `goal_candidate` observes, model **spammed `confirm_localization`** (denied) instead of shifting to early150 probes.
- Guard added post-hoc: confirm-spam → rule recovery; confirm requires shot+net evidence.

### Relations

- Independent review accepts temporal; causal without evidence downgraded/rejected.
- Rule/agent terminal relations used temporal (+ weak narrative), not auto-causal score edges.

## 5. Acceptance vs goals (honest)

| Criterion | Status |
|--|--|
| More accurate goal action than R1 | **Partial** — go-ahead error ~149s→~25–27s (Rule/targeted); strict recall still **0** vs weak refs; strict Gold empty |
| DeepSeek mid-loop search | **Yes** (Agent llm_mid=17); but poor tool choice vs Rule on full match |
| Relations with evidence; no score-order causal | **Yes** (reviewer + no rule auto-causal) |
| Event-Agent value vs Rule/Fixed | **Not demonstrated on Croatia full match recall**; autonomy yes, localization **no**. Fixed proximity ≠ verified action |

**Unresolved kept.** No tolerance widening (±90s not restored). No Story Graph / render.

## 6. Costs (real HTTP estimates)

| Run | est_cost_usd |
|--|--|
| Targeted agent1/2 | ~0.021 + ~0.021 |
| Rule2 full | ~0.027 |
| Agent full | ~0.038 |
| **Round2 real total (approx)** | **~$0.11** |

## 7. Deliverables

```
round2_croatia/
  audit_r1/round2_audit.json
  audit_r1/action_localization_eval.json
  round2_comparison.json
  autonomous_search_trace.json      # from Agent full
  relation_verification.json        # from Agent full
  cmp_fixed_*/ cmp_rule2_*/ cmp_agent_*/ (+ review_pack)
docs/STORY_VA_V2_EVENT_GUIDED_ROUND2_REPORT.md
```

## 8. Next (if continuing)

1. Prefer `virtual_early150_*` in Agent system prompt + hard block confirm without evidence (done) + unit test for spam recovery.  
2. Multi-hypothesis observe around lag probes before confirm.  
3. Human-confirm V1 windows → populate strict Gold.  
4. Only then re-judge Agent vs Rule on strict metrics.
