# Story Video Agent V2 — Strip-Guided Round 1

**Baseline:** `story-va-video-driven@83dcbc6` (+ this commit)  
**V1 freeze:** Tag `story-va-v1.0-structured-baseline` @ `462ea11` (unchanged)  
**Event-Guided modules:** preserved  
**render_ready:** `false`

## Architecture

```
MP4 + human_corrected events.json
        ↓
8.31 causal_chain6 (production, rule-only, no Qwen)
        ↓
upstream strip.json  →  v2_strip_adapter  →  predicted_strip_chains.json
        ↓
Strip-Guided Story Agent (DeepSeek mid-loop + Qwen strip windows)
        ↓
story_candidates / beats / relations / localized_clips / agent_trace
```

Human `*_causal.json` / strip gold / V1 story roles were **not** used as model input.

## Upstream strip inference (Croatia)

| Item | Value |
|--|--|
| Events | `2022-11-28 克罗地亚vs加拿大.json` (159) |
| Engine | `AlgoStripAdapter` → `causal_chain6.strip_pipeline` |
| Profile | `production`, `use_llm=False`, sliding recall on |
| Output | `.../croatia_r1/upstream_strip/strip.json` (+ `strip_raw_clips.json`, `timeline.json`) |
| Predicted chains | **62** |
| Categories | special 45, danger 14, correction 2, outcome 1 |

### Key-goal coverage (offline only; weak centers)

| Weak center | Nearby strips (±90s) | Outcome/goalish? |
|--|--|--|
| ~979s opening | **0** | No |
| ~3065s equalizer | 2 (快发定位球 / 手抛球) | No |
| ~3522s go-ahead | 1 (快发定位球) | No |
| ~6322s extend | 2 (射门扑救 / 手抛球) | No |

**Finding:** production rule-only strips **do not** emit clear goal chains for the four T01 scoring moments. Nearest signals are danger/special chains (shot-save, throw-in, quick restart). One `outcome_other` appears near ~7747s (late goal era). This gap is recorded, not patched with gold.

## Adapter

`v2_strip_adapter.py` → `predicted_strip_chains.json`

- `prediction_source=causal_chain6_predicted`
- `verification_status=unverified` until video confirms
- Keeps template/label/prob_top1/margin only when present upstream
- Diagnostics for missing event-id mapping / overlaps; refuses gold/causal payloads

## Strip-Guided agent run

**Out:** `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r1/agent_20261029_120949`

| Metric | Value |
|--|--|
| discovery_status | story_candidate (score anchors 0:1→…→4:1) |
| DeepSeek | mid-loop `llm_mid`×8 (not terminal-only) |
| Qwen observes | focused on strips near ~3700s (go-ahead score era) |
| Verified strips | **0** |
| Localized edit clips | **0** |
| Relations | 78 temporal+narrative (no causal invented from score order) |
| Frames | 48 |
| Real HTTP | 13 |
| est_cost_usd | **~$0.032** |
| elapsed | ~293s |

### Evidence honesty

Qwen often saw **shot XOR net** in short windows → stayed `goal_candidate` / `unresolved` under frame-bound rules (keyword-only insufficient). No automatic upgrade to verified.

Beats were assembled from predicted priority strips + score path; **not** equivalent to V1 role-labeled goal actions, and not claimed as clip-ready.

## Deliverables checklist

| Artifact | Path |
|--|--|
| Raw strip | `croatia_r1/upstream_strip/strip.json` |
| Adapted strips | `.../predicted_strip_chains.json` |
| story_candidates.json | agent run dir |
| story_beats.json | ✓ |
| story_relations.json | ✓ |
| localized_story_clips.json | ✓ (empty clips — unresolved) |
| story_agent_trace.json | ✓ |
| Report | `docs/STORY_VA_V2_STRIP_GUIDED_ROUND1_REPORT.md` |

## Distinction of evidence layers

1. **Upstream predicted strips** — algorithm hypotheses (62).  
2. **Video-verified actions** — none confirmed this round.  
3. **DeepSeek global story** — T01 candidate from score anchors + strip selection; relations temporal/narrative.  
4. **Missing / wrong strips** — opening uncovered; key goals lack outcome templates.

## Ready for Story Graph / auto-edit?

**Not yet.** Blockers:

1. Strip predictions miss critical goal chains under production rule-only.  
2. Zero verified localized clips → no trustworthy EDL seeds.  
3. Beats not yet grounded in verified media intervals.

Possible next steps (not done here): strip profile/recall tuning without gold injection; denser multi-window verify per danger strip; optional LLM strip classify (still not human causal).

## Tests

```bash
PYTHONPATH=10.27scasual_chain/algo python3 -m unittest \
  story_video_agent.test_v2_strip_guided story_video_agent.test_v2_event_guided -q
```
