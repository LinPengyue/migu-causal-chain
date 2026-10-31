# STORY_VA_V2 G0 — Architecture Audit (T01 cross-match readiness)

**Audit HEAD (pre-G0 commit):** `406f4f5003064341fd53c426687d747f30d5ba93` on `story-va-video-driven`  
**Scope:** code-level audit only; no cross-match inference, no paid API, no new renders, no V1 / independent 8.31 edits.  
**Croatia R2.9 freeze:** `render_ready=false`, `visual_qc_pass=false`, `blocked_source_corruption=true` (match-local media exception; not a universal G1 blocker).

## 1. Real data flow (as implemented)

```
MP4 + raw events.json
  → v2_event_adapter.load_events_json (whitelist; refuse causal top-keys)
  → v2_score_transitions / score anchors on score_pair
  → v2_missing_goal_detector.detect_missing_goals
  → v2_goal_recovery_runner / R2.3 CLI verify (VLM optional; cache by event_id)
  → predicted strips (8.31 algo root via --algo-root; DEFAULT points at Croatia-era path)
  → v2_strip_guided_r2_3_planner (+ ensure_verified_goals_selected)
  → story graph / memory
  → v2_strip_guided_r2_6|8|9_build_edl  ← Croatia-shaped final EDL
  → r2_7 render + r2_8 visual QC / Live-Only gates
```

V1 Phase 5 A/B packages under `reports/phase5/{uae_oman,osasuna_celta}/` are **historical causal-dependent outputs**, not V2 proof.

## 2. Module table

| Module | Entry | Input schema | Output | Callers | Hard deps | Cross-match risk | Evidence |
|--------|-------|--------------|--------|---------|-----------|------------------|----------|
| `v2_event_adapter.py` | `load_events_json` | events.json; `input_source∈{human_corrected,upstream_detected}` | sanitized events + digest | R2.3 CLI, recovery | Path JSON | **Reusable** if path is raw events; causal top-keys rejected | L16–57, L157–207 refuse `causal_chains` / story keys |
| `v2_score_transitions.py` | `analyze_score_transitions`, `independent_discovery_check` | score timeline rows | deficit/eq/go-ahead + status | discovery / recovery | none match-specific | **Partial generic**: first-deficit lock; **B last-arc right protagonist NOT modeled** | L103–219; A→`story_candidate` left; B first-arc left @2:1, ignores 2:2→2:3 right |
| `v2_missing_goal_detector.py` | `detect_missing_goals` | sanitized events (+ optional strips) | `missing_goal_candidates` | recovery / R2.3 | Goal type set | **Reusable intent**; A/B have ~0 typed `Goal` → recovery mandatory | L13–19 `GOAL_TYPES`; L302+; docs forbid causal/gold L491+ |
| `v2_goal_recovery_runner.py` | assemble beats / run recovery | candidates + video | verified/unresolved goals; `render_ready=false` | CLI | video + optional VLM | Generic assembly; causal never from score alone | L67, L154, L216 |
| `v2_strip_guided_r2_3_cli.py` | `main` | `--video`, `--events`, `--r22-dir`, `--reuse-verify-cache`, `--input-source` | out_dir reports | operator | **DEFAULT_R22 = Croatia unified dir**; probe `/tmp/croatia_vlm_probe` | **P0 cache/default pollution** | L44–47, L112–120, L167–201 |
| `v2_strip_guided_r2_3_planner.py` | planner + `ensure_verified_goals_selected` | memory / strips / keys | beats / relations | CLI | LLM optional | Mostly generic T01 language; still Croatia-tuned prompts possible | L441+ |
| `v2_strip_guided_r2_6_build_edl.py` | build EDL | verified goals list | EDL | Croatia pipeline | **`len(goals)!=5` hard fail**; title 克罗地亚; `g01..g41` | **Not reusable as generic EDL** | L13–14, L65–66, L178 `all_five_goals_*` |
| `v2_strip_guided_r2_8_build_edl.py` | Croatia R2.8 EDL | hardcoded PTS | EDL | R2.8 | Fixed g01/g11/g21/g31/g41 PTS, 4:1 ending | **Match-local only** | L57 title; L59–149 segments; L195 |
| `v2_strip_guided_r2_9_build_edl.py` | patch R2.8 | R2.8 EDL | trimmed g11/g21; g31 blocked | R2.9 | Croatia PTS 3074.5 / 3521 / 6315 | **Must not copy to A/B** | L21–78 |
| `v2_strip_guided_r2_7_render.py` | render from EDL | EDL + MP4 | MP4 | QC path | ffmpeg | Generic if EDL generic | — |
| `v2_strip_guided_r2_8_visual_qc.py` | frame QC | rendered MP4 | pass/fail features | deliverability | corruption heuristics | Heuristics reusable; Croatia exception windows are not | band/macroblock detectors |

## 3. Confirmed generic vs Croatia-only

### Confirmed reusable (with caveats)

- Event whitelist adapter + causal top-key refusal.
- Scoreboard parse / trajectory builder (not Croatia score literals).
- Missing-goal candidate emission from score deltas without gold times.
- Recovery runner’s “no causal from score order alone” + `render_ready=false` defaults.
- Visual QC feature detectors (neon/band/macroblock) as **media-agnostic** tools.

### Croatia / five-goal specials (do not ship as “generic V2”)

- R2.6–R2.9 EDL composers (five goals, Chinese Croatia title, fixed PTS, `all_five_goals_verified_first_live`).
- CLI `DEFAULT_R22` Croatia output dir; VLM preflight image under `/tmp/croatia_vlm_probe`.
- Verify-cache reuse keyed by `event_id` folder only — **no** `match_id` / video / events / strip hash binding.
- R2.9 source-corruption trim windows are single-match exceptions.

### NOT_VERIFIED (source exists ≠ capability proven)

- End-to-end T01 on A or B with **only** MP4 + raw events + fresh 8.31 predicted strips (G0 did not run).
- Live-Only correctness on A/B broadcast overlays.
- Whether 8.31 auto strips for A/B in `reports/strip_dump*` are algorithm-predicted without gold leakage when fed to V2 (historical dumps exist; **must not** be treated as G0 validation).
- Planner quality on right-side last-arc (B) and mid-match three-goal arc (A).
- France–Australia as executed V2 case (MP4 now present; still **not** run).

## 4. Input authority

| Allowed | Forbidden for V2 inference / cache / eval labels |
|---------|-----------------------------------------------------|
| Raw `*.json` events (`human_corrected` or `upstream_detected`) | `*_causal.json`, `strip_gold.json`, `highlight_gold*.json` |
| Match MP4 | V1 EDL goal times / Phase5 story roles as supervision |
| Independent 8.31 **predicted** strips (fresh or proven non-gold) | Using gold to tune thresholds mid-run |

Datasets under `datasets/matches/{A,B}/` currently contain **gold/timeline only** — usable as offline human review later, **not** as V2 model input.

## 5. G0 synthetic isolation (non-production)

Added (no change to R2.x EDL/render outputs):

- `algo/story_video_agent/v2_g0_cross_match_preflight.py`
- `algo/story_video_agent/test_v2_g0_cross_match_preflight.py`

Covers: cache binding reject, forbidden filenames/keys, variable goal-count T01 skeleton, right-side / no_comeback synthetic classification. All leave `render_ready=false`.
