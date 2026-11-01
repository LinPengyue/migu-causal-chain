# STORY_VA_V2 G1 — Implementation Report

**Branch:** `story-va-video-driven`  
**Base HEAD before G1 code:** `c80d2ee71da7a938344fe75304098301d2e43a14`  
**API/token spend:** **0**  
**Production Croatia R2.6–R2.9 EDL builders:** left unmodified (guarded, not called for A/B)  
**V1 / independent 8.31 source:** not modified (8.31 used read-only via `AlgoStripAdapter.predict`)

## 1. P0 fixes wired into real entrypoints

| P0 | Change | Production wiring |
|----|--------|-------------------|
| Cache / identity isolation | Extended `v2_g0_cross_match_preflight.py` with `normalize_match_id`, `assert_match_id_consistent`, `build_strip_provenance`, `validate_strip_bundle_provenance`, `assert_verify_cache_entry` (fail-closed on missing provenance) | Used by **`v2_g1_cross_match_cli.py`** and **`v2_strip_guided_r2_3_cli.py`** verify-cache path |
| No Croatia default for cross-match | New generic CLI has **no** `DEFAULT_R22` / no `/tmp/croatia_vlm_probe` | `v2_g1_cross_match_cli.py` requires `--match-id/--video/--events/--out-dir` |
| Legacy CLI protection | `v2_strip_guided_r2_3_cli.py` aborts if `DEFAULT_R22` Croatia dir is used for non-Croatia `match_id`; rejects causal/gold filenames; verify-cache requires provenance bind | Integration test `test_r23_refuses_default_croatia_r22_for_other_match` |
| Last-deficit arc | `analyze_last_deficit_arcs` / `select_last_deficit_arc` in `v2_score_transitions.py` | Called inside G1 CLI → `selected_arc.json` feeds story graph + generic EDL |
| Generic N-goal EDL | New `v2_generic_edl_composer.py` (`structure_only` / `video_verified`); `refuse_croatia_edl_builder` | G1 CLI writes `candidate_edl.json` at `structure_only`; never `verified_first_live` without video evidence |
| Missing goals stay unresolved | Detector candidates forced `verification_status=unresolved` when API=0 | A: 3 unresolved; B: 5 unresolved; `n_video_verified_goals=0` |

## 2. New / touched files

- `algo/story_video_agent/v2_g1_cross_match_cli.py` — **generic production entry**
- `algo/story_video_agent/v2_generic_edl_composer.py`
- `algo/story_video_agent/v2_score_transitions.py` — last-deficit arcs
- `algo/story_video_agent/v2_g0_cross_match_preflight.py` — production gates
- `algo/story_video_agent/v2_strip_guided_r2_3_cli.py` — cross-match refuse + cache bind
- `algo/story_video_agent/test_v2_g1_cross_match_integration.py` — **15** integration/unit tests on real CLI/composer paths
- Docs: this file + A/B dry-run + transfer comparison

## 3. Tests (repeatable)

```bash
cd /tmp/migu-va2c   # or repo root
PYTHONPATH=10.27scasual_chain/algo \
  python3 -m unittest \
  story_video_agent.test_v2_g0_cross_match_preflight \
  story_video_agent.test_v2_g1_cross_match_integration -v
```

**Result:** 26 tests OK (11 G0 + 15 G1). Includes CLI abort on causal filename, match_id mismatch, gold strip dump, legacy Croatia R22 misuse, B synthetic right last-arc, A-like structure dry-run.

## 4. Dry-run command template (A/B)

```bash
PYTHONPATH=10.27scasual_chain/algo \
python3 -m story_video_agent.v2_g1_cross_match_cli \
  --match-id '<events.match_id>' \
  --video '<mp4>' \
  --events '<raw events.json>' \
  --out-dir '/data2/lpy1/_story_va_outputs/v2/cross_match_g1/<run>' \
  --algo-root '/data2/lpy1/causal-chain2/8.31causal_chain' \
  --input-source human_corrected
```

`--real` is hard-aborted in G1. Gold `strip_dump` dumps are rejected by provenance (`mode=gold_clips`). Strips come from **raw-events reinfer** (`reinfer_A_original`).

## 5. Exceptions / honesty

- Zero-API ⇒ no video-verified goals; structure EDL placeholders only. **Not** a story delivery.
- Historical A/B `reports/strip_dump*` are gold_clips — **not used**.
- No causal/gold/Phase5 inputs in provenance (`forbidden_inputs_used=[]`).
- `render_ready` remains `false` everywhere.
