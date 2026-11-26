# R3 — common Story Graph, source-bound materialization and initial EDL

Frozen R2b/R2c baseline: 73078bbe319bf4b9eccd5004b291d1d61350520b.
Frozen R2a.4 baseline: 0bba8b799e39d35305663d2497683c2602690950.
No historical algorithm or artifact changes. No model, video, or reference access.

## Design

- story_graph_compiler.py: normalize all five operator outputs into anchor,
  missing, transition and context nodes; retain original candidate, role
  distinctions, typed upstream edges and task references. A score
  confirmation or phase search region is not a media interval.
- story_materializer.py: rebuild windows from the same source atomic IDs,
  require LIVE annotation and valid bounded source times, union only
  overlapping/touching windows; each event occurs at most once per draft.
  Multiple semantic roles can share one physical material. Disjoint
  windows remain separate; no gap fill or arbitrary padding.
- Relation paths: a unique path retains every intermediate member;
  multiple paths retain common intermediate members in the initial draft
  and all alternative paths as hypotheses. No arbitrary best-path claim.
- Context pool: merge identical physical membership into one candidate,
  preserving multiple semantic perspectives. Unselected context nodes
  and edges are available for Story-First; no automatic insertion.
- R3 initial EDL is anchor-first (plus path intermediate members), not a
  narrative-complete edit. Every segment is preview-only, unverified.
  Structural completeness only means required nodes have materials.
- r3_story_pipeline.py: batch compiler over R2a.4 and R2bc saved outputs,
  separate story folders and metrics; retain all global observation tasks,
  attach directly linked and evidence-relevant tasks to individual stories.
  Mixed score-context hypotheses remain ineligible for strict threat metrics.

## Existing V3-R comeback EDL

Use the original A/B V3-R historical EDL JSON if accessible on the server.
Do not run the historical pipeline again or substitute a newly generated
EDL. Identify the actual source run, original source video and protagonist.
The research connector has not located the real A/B native EDL files;
server evidence is required. Supply one manifest per source, e.g.:

    {
      "schema": "sportscausal_legacy_seed_manifest_v1",
      "seeds": [
        {
          "story_id": "comeback:1",
          "video_id": "EXACT_EVIDENCE_VIDEO_ID",
          "subjects": ["team_1"],
          "path": "/actual/server/path/native_edl.json",
          "sha256": "ACTUAL_SHA256",
          "source_provenance": "original run path, commit and source mapping"
        }
      ]
    }

B subject is team_2 based on the frozen comeback result. Manifest is an
explicit provenance declaration, not an automatic filename-based match.
For a wrapped native JSON object supply edl_key for its top-level segment
list; for non-default time field names supply time_fields, in/out order.
Native JSON is stored byte-for-byte as legacy_seed.json with metadata.
It remains an independent Agent seed and comparison baseline; the new
initial_edl.json is not a replacement. Source mapping, segment timing and
hash are checked; no inheritance of first-live verification. If unavailable,
omit the manifest, report legacy_seed_not_supplied, and do not call the
anchor-only draft a replacement or equivalent to V3-R.

## Cursor: one combined run per match

    cd research/sportscausal
    python -m unittest -v test_r3_story_pipeline

Expected 12 new tests; report actual results.

    python r3_story_pipeline.py \
      --evidence artifacts/stage1_2_evidence_preflight_20261125/A_uae_oman/keeper_rescue/evidence.json \
      --r2a4-dir artifacts/v3r_general_r2a4_preflight/A \
      --r2bc-dir artifacts/v3r_general_r2bc_preflight/A \
      --allow-dev --out-dir artifacts/v3r_general_r3_preflight/A

For B replace paths accordingly (B_osasuna_celta). Append
--legacy-seed-manifest ACTUAL_MANIFEST if recovered before running.
No historical reruns, no paid calls, no render, no manual candidate edits.

## Audit

- Expected frozen inputs: 13 original-type candidate stories across A/B
  and 2 separately marked mixed score-context hypotheses. Do not force counts.
- A turnover_to_goal: preserve all 7 IDs including 5 intermediate members;
  report exact source union intervals, no invented footage between them.
- B equalization:1 missing score:2 must remain a missing graph node, no
  material or EDL, linked to observe:5; structurally incomplete.
- Phase switch search interval [1922.55,1955.54] must not become a clip.
- Check every segment's source and bounds, no annotated nonlive atoms,
  no duplicate events within a story, chronological nonoverlap, no
  fabricated windows. Compare union of actual atomic windows.
- A/B comeback context includes dual perspectives without duplicate
  physical material. Context pool is unselected. Lead-preservation
  diagnostic remains weak signature, not verified defensive evidence.
- All 20 existing global tasks retained; report per-story direct vs
  contextual refs. No task executed. All first-live/release flags false.
- If legacy recovered, compare byte hashes, segment counts and duration
  against original. Show anchor-only new draft separately; confirm actual
  agent seed provenance. If not recovered, record blocker, don't rerun.
- Return all per-story files, summary.json, global observation_tasks.json,
  unittest.txt, REPORT.md, input hashes and exact commands under
  artifacts/v3r_general_r3_preflight/.

R3 does not prove narrative quality or produce a releasable highlight.
A/B are HUMAN_ATOM_ENRICHED_DEV. Further development integrates Observer,
Planner, Verifier and Story-First, then cross-match/held-out validation.
