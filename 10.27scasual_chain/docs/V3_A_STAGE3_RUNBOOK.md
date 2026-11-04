# V3-A Stage-3 Runbook — France P0 bounded evidence search

Date: 2026-11-04. Branch: story-va-v3-a.

## Immutable baseline

V3-R frozen code branch: story-va-v3-r-frozen-20261103, commit 2d1ec9c2a409e681aec9942332b3509fe054b887. A/B/C/France Phase5 artifacts are read-only. This Stage-3 tool is not wired into Phase5 and never edits or rerenders any EDL/MP4.

Stage-1 result: France missing opponent opening goal, a P0; A/B/C structural proxies passed. Stage-2 result: 21/21 tests pass, only France selected issue_000; T01 score-confirmation anchor 1535.65s, 7 search windows covering 1355.65–1550.65s, each ≤30s, within source duration 7305.555s. Rejected Goal@1351 is NOT ground truth.

## Stage-3 first increment — code written, local tests and real source run not yet executed

Module: algo/story_video_agent_v3/stage3_evidence.py
Tests: tests/test_v3a_stage3_evidence.py (12 new cases, not yet confirmed passed)

The Stage-3 entry rejects changed input SHA-256, altered canonical task/windows, cross-match mismatch, altered Phase5 source video path, invalid video duration/windows, and task sets other than one P0 missing opponent-opening action.

Default FRAMES_ONLY mode, no API: use original V1 FrameStore and FFmpeg to sample 3 per 30s window, global budget max 24 (France uses 21). Frame records preserve requested media sec, decoded PTS when available, PTS drift, and frame provenance. Optionally produce a source-time-labelled JPG contact sheet via Pillow. Missing PTS or >2s discrepancy is flagged, not silently trusted.

Outputs in a NEW folder outside frozen Phase5:
- stage3_evidence.json
- frame_manifest.json
- frames/ (sampled JPEGs)
- contact_sheet.jpg (if Pillow installed)

The default report ALWAYS preserves first_live_goal_verified=false, semantic_coverage=UNKNOWN, edl_modified=false, render_ready=false, release_decision=NOT_AUTHORIZED. Sparse frames cannot prove a goal's absence.

### Local tests

PYTHONPATH=10.27scasual_chain/algo python -m unittest discover -s 10.27scasual_chain/tests -p 'test_v3a_*.py' -v

### Local source-video sampling

ROOT=/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_FR_france_australia_zeroshot
PHASE5="$ROOT/04_phase5"
VIDEO=$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["inputs"]["video"])' "$PHASE5/phase5_manifest.json")

PYTHONPATH=10.27scasual_chain/algo python -m story_video_agent_v3.stage3_evidence \
  --phase5-dir "$PHASE5" \
  --proposal "$ROOT/v3a_stage2_planner_proposal.json" \
  --video "$VIDEO" \
  --out-dir "$ROOT/v3a_stage3_france_probe_01"

Do not reuse an existing output path. Do not use a rendered story MP4 as the original source. First verify 21 expected frames (or report actual failures) and PTS status. Then inspect contact_sheet.jpg and relevant *contiguous source video segments*, especially for first LIVE vs replay. Source scoreboard confirmation cannot substitute for goal action.

### Real VLM mode — optional interface only, NOT approved for initial test

Requires both --enable-real-vlm and --approve-api-cost plus STORY_API_ENABLE=1 and vision provider credentials. Limit to first/middle/last window (up to 3 provider calls), with max estimated soft $0.50 / output-token cap 640. Calls incur actual API charges; the estimate is not an invoice cap. Do not invoke until explicit approval after the FRAMES_ONLY run. VLM output is observation-only; never use it to certify first LIVE or EDL edit.

### Next gate

Cursor reports 1) all Stage-1 + Stage-2 + Stage-3 unit tests; 2) unchanged upstream hashes; 3) actual frames/PTS result; 4) manual contact-sheet findings; 5) candidate intervals or an explicit UNKNOWN; 6) whether targeted finer sampling is justified.

No automatic repair/loop integration yet. Only after those evidence checks should Planner feedback refine windows and (separately) a verified Composer patch be evaluated against the V3-R baseline.
