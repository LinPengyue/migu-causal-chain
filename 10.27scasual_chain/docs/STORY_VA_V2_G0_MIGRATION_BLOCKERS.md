# STORY_VA_V2 G0 — Migration Blockers (P0 / P1 / P2)

**HEAD audited:** `406f4f5` (`story-va-video-driven`). Evidence from static code + inventory; no A/B inference.

## P0 — Must fix before any cross-match formal run

### P0-1 Fixed five-goal EDL hard fail

- **Where:** `v2_strip_guided_r2_6_build_edl.py` L13–14, L65; flags L178 `all_five_goals_verified_first_live`.
- **Snippet:** `if len(goals) != 5: raise ValueError(...)` then unpack `g01,g11,g21,g31,g41`.
- **Impact:** Match A (~3 goals) / B (~5–6 score steps, ≠ Croatia five verified lives) crash or wrong structure if this composer is reused.
- **Minimal repro:** Call R2.6 builder with 3 verified goals → `ValueError`.
- **Minimal fix (G1):** New generic EDL composer parameterized by N verified T01 goals + dynamic titles; keep R2.6–R2.9 as Croatia-only.

### P0-2 Croatia-hardcoded R2.8 / R2.9 PTS EDL

- **Where:** `v2_strip_guided_r2_8_build_edl.py` (title L57; segments ~L59–172; 4:1 ending); `v2_strip_guided_r2_9_build_edl.py` L21–78 (3074.5 / 3521 / g31 BLOCK).
- **Impact:** Feeding A/B video through these modules yields Croatia times / wrong story / silent nonsense.
- **Minimal repro:** Inspect module — no video/events args; fixed floats.
- **Fix:** Do not call R2.8/R2.9 for other matches; gate CLI by `match_id`.

### P0-3 DEFAULT_R22 + verify-cache without media identity

- **Where:** `v2_strip_guided_r2_3_cli.py` L44–47 `DEFAULT_R22` → Croatia unified dir; L112 default; L167–190 reuse `verify_{event_id}/original_goal_verify.json` with **no** match/video/events/strip hash check; L201 `/tmp/croatia_vlm_probe`.
- **Impact:** Wrong-match verified goals / strips if operator omits `--r22-dir` or points `--reuse-verify-cache` at Croatia cache with colliding event_ids.
- **Minimal repro:** Run CLI help defaults; inspect reuse loop — only `event_id` path key.
- **Fix:** Require explicit `--r22-dir` (no Croatia default) OR refuse default when `--video` match_id ≠ Croatia; cache key = `match_id|video_sha256|events_sha256|strip_provenance`; reject mismatch (see G0 preflight `assert_cache_binding`).

### P0-4 Last-deficit / right-side protagonist incomplete

- **Where:** `v2_score_transitions.analyze_score_transitions` L118–194 locks **first** `deficit_side`, then first lead-after-that-deficit.
- **Impact on B:** Board `0:0→0:1→1:1→2:1→2:2→2:3` analyzed (adapter smoke) as left `story_candidate` with go-ahead `(2,1)`, **missing** Celta right last arc `2:1→2:2→2:3`.
- **Minimal repro:** Feed unique timeline for B scores into `analyze_score_transitions` (done in G0 inventory).
- **Fix:** Add `last_deficit_arc` / multi-arc selector: protagonist = side that trails then leads in the **final** T01 window; keep first-arc as secondary.

### P0-5 Near-zero typed Goal events → must not skip recovery

- **Where:** A/B raw events: A has 0 true Goal types (only `Goal_line_clearance`); B has 0 Goal-typed; scores live on non-goal rows.
- **Impact:** Pipeline that assumes Goal events exist will under-select beats or invent from causal (forbidden).
- **Fix:** G1 must run missing-goal + video verify path; unresolved → no fake verified; no render_ready upgrade.

### P0-6 Gold / causal adjacency risk

- **Where:** `datasets/matches/{A,B}/` = gold only; `交付_out/*_causal.json` sit next to events; Phase5 graphs exist.
- **Impact:** Accidental `--events` pointing at causal or strip_gold pollutes V2.
- **Mitigation already partial:** adapter refuses causal top-keys; G0 preflight rejects `*_causal.json` / `strip_gold.json` filenames.
- **Fix:** CLI path guard + refuse basename patterns before load.

## P1 — Runnable risk / weak story if deferred

### P1-1 OCR / score noise (B)

- Inventory saw scoreboard token `1：！` in transitions — can insert bogus states if parser is loose.
- **Fix:** tighten invalid pair reject; prefer LIVE non-replay anchors (detector already prefers live board).

### P1-2 Non-goal strip count / beat stuffing

- Planner / graph may still bias toward Croatia-like strip counts; `ensure_verified_goals_selected` helps but unproven on A/B.
- **Fix:** after generic EDL, allow omitting weak setup strips; never force all goals into one beat without evidence.

### P1-3 Live-Only / replay conservatism on new broadcasts

- Overlay / REPLAY flags differ by league; Croatia corruption whitelist must not travel.
- **Fix:** per-match empty exception list by default.

### P1-4 8.31 strip provenance

- Historical `strip_dump*` / `reels_dump*` exist for A/B under causal-chain trees; G0 did not prove they are gold-free for V2.
- **Fix:** G1 regenerate or hash-tag `strip_provenance=algo_predicted:<run_id>`; refuse gold strip paths.

### P1-5 Dynamic titles / score graphics

- R2.8 hardcodes Chinese Croatia title; A/B need team names from events `teams`.
- **Fix:** template from `match_id` / teams metadata.

## P2 — Presentation / style (non-blocking for correctness)

- Croatia-specific QC narrative notes in R2.9 JSON.
- Probe image path naming (`croatia_vlm_probe`).
- Phase5 report layout differences vs V2 deliverables.

## Priority order for G1

1. Cache + default isolation (P0-3) + filename guards (P0-6)  
2. Last-deficit arc API (P0-4)  
3. Generic N-goal EDL (P0-1) and hard-gate R2.8/R2.9 to Croatia only (P0-2)  
4. Missing-goal recovery mandatory when typed goals < score deltas (P0-5)  
5. Then A dry-run (still `render_ready=false` until human QC)
