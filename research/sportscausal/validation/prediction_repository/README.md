# Story Agent Prediction Repository (FanEdit v1.1)

FanEdit is the downstream evaluation benchmark, NOT an inference component.
Do not give the Agent human reference stories, reference clips or evaluation
feedback when generating the predictions. The data and evaluator stay frozen:
v1.1 e67d7c9f596db5b3cd5618f4692733126e68b1c1; evaluator v2
db25a77fe7d6b66f28abf8e9ae20ade67df1be98. This archive is separate from both.

## Historical data saved without new inference

- historical_native_story_outputs.jsonl: A keeper V0/V1/V2/V3 + native final,
  C lead_preservation R3. A native final equals V0 (formal delivery blocked);
  V3 is the 150.93s research preview, not the native final.
- Croatia_native_comeback_outputs.jsonl: actual Croatia V0/V1/V2 from
  7235ca7. Source SHA and historical input tier require server verification.
  Do not promote that preview to certified final or mix versions.
- C_native_causal_outputs.jsonl: all 78 8.31 and 80 adapted C predictions,
  separately, including failed/unsupported chains. C has no Agent output.
- Registry: prior A/B legacy seed hash references and four comeback run
  references. Remaining historical final outputs and MP4s are on server
  and must be recovered without reruns. Missing files remain missing.

Each archive row has immutable artifact commit/blob identity and native EDL or
chain. These are actual predictions, not FanEdit scores. Historical Git blob
IDs are not media SHA256. Preserve the originals, not regenerated replacements.

## New runs: after inference, build export spec and export

Use the separate native development case inputs and run the six remaining
template validations according to the existing Agent pipeline. The earlier
case shortlist utility is optional for development case selection only; never
treat selected-reference cases as formal held-out benchmark. Do not run the
evaluator as an Agent loop. Reuse previous outputs if inputs and version match.

From research/sportscausal:

    python -m py_compile export_fanedit_predictions.py build_fanedit_export_spec.py
    python -m unittest -v test_export_fanedit_predictions

Prepare a source-binding JSON with exact match_id, benchmark video_id,
native_video_id, source_sha256, identity_provenance (verified source mapping),
and timeline="source_video_media_seconds". No filename-only guess or
half-match offset. Example for C, after checking existing trusted source:

    {
      "match_id": "FH-35DA83FD",
      "video_id": "FH-35DA83FD-Vf6d7ce5566bc",
      "native_video_id": "10月20日 25-26赛季西甲第9轮 莱万特VS巴列卡诺 国语",
      "source_sha256": "5ab8ee77ed0d0cb56f020348d4c73b4c27c738f6285db941e1797f87bb1d4d73",
      "identity_provenance": "verified intake and frozen source inventory; confirm actual pairing on server",
      "timeline": "source_video_media_seconds"
    }

    python build_fanedit_export_spec.py \
      --fresh-dir "$FRESH_RUN_DIR" --source-binding "$SOURCE_BINDING_JSON" \
      --run-id "$RUN_ID" --out "$NEW_SPEC_JSON"

For each executed Agent candidate add --agent-dir "$ACTUAL_AGENT_RUN_DIR"
(repeatable). This collects all original R3 candidates, 8.31 and adapted
causal predictions, available V0, outer previews and native final EDLs.
Records unattempted candidates and zero template counts; mixed score-context
diagnostic is separately indexed, not a ninth story type. A complete Agent
attempt count does not establish successful output or coverage of a benchmark.

    python export_fanedit_predictions.py \
      --spec "$NEW_SPEC_JSON" --benchmark-dir "$FANEDIT_V11_DIR" \
      --out-dir "$NEW_EXPORT_DIR"

For historical legacy runs lacking fresh manifests, prepare a spec with
schema=sportscausal_prediction_export_v1, run_id, algorithm_commit,
input_tier, match_id, source (same binding), actual elapsed/cost metadata,
and artifacts. Each artifact has path, sha256, stage, variant, and for
story, template_id and candidate_id. Use unique variant per version.
Check historical artifact identity against Git and/or old source manifests
before supplying actual SHA256. Preserve historical native final separately
from selected preview even if final is blocked. No paid rerun.

## Outputs and blockers

- native/: original file bytes, SHA256 checked;
- *.audit.jsonl: native predictions, mapped representation, explicit issues;
- *.projected_diagnostic.jsonl: one row per native prediction, even if blocked;
- *.strict.jsonl: emitted ONLY if every prediction in that task/stage/variant
  is representable under the pinned evaluator contract;
- export_manifest.json: provenance, groups, counts, partial/blocked status.

Projection reads only pinned videos.jsonl, atomic_events.jsonl, taxonomy.json,
not reference chains. Uses native IDs (video_id:E:source_event_id) and overlap
checks. Never matches to a gold clip or invents an ID for atom_fill. Unknown
labels, unavailable IDs, empty or out-of-window events and invalid intervals
block strict export. Missing source-less inserted bridge video ID can inherit
only the explicit single-source binding. Preserve EDL array order, active
timed segments, duplicate IDs; record explicit inactive edits and untimed
title cards excluded from source-segment scoring. Preserve replay predictions
for accountability; format-valid is NOT quality-valid.

Causal label mapping includes only currently explicit mappings; review any
unmapped detector templates against frozen 18-type definitions, not gold
matches. Optional reviewed_causal_mapping records exact native category,
native subtype, public category/subtype and mapping provenance. Unknown
labels must not be silently relabeled. Raw strip t0_ms/t1_ms are converted
to seconds, not stretched to reference windows. This is the declared
prediction interval convention; do not change it per case.

The v2 evaluator currently rejects unregistered and out-of-window IDs and
requires nonempty event lists. Thus atom_fill-only windows may be impossible
to score using strict v1.1 input without a separately agreed common event
grounding protocol. Do not erase them or fabricate a replacement. Report
coverage and preserve native outputs; resolve evaluator protocol separately.
No full-scope metrics from incomplete, template-conditioned, gold-derived
or mixed-version runs. Full cohort scoring must include zero-output cases
and actual per-match wall time/cost; missing efficiency logs remain null.
A/B/C and other exposed matches are development records, not held-out results.

## Cursor next step (zero HTTP export work)

Sync research branch (no force reset). Run the 8 export tests; build and
export C using its already complete fresh_general_v1, no inference. Return
manifest and all mapping blockers. Verify A keeper and Croatia historical
artifacts, recover original A/B/FRA comeback final EDLs and native audits
from server without reruns. Export separately with actual tier, source
identity and version. Then proceed with six E2E case preparation and real
Agent runs only under authorized budgets. Automatically export each new
completed run; do not wait for future full Benchmark scoring.
