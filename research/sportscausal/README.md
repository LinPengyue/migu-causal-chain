# SportsCausal — template generalization, Stage 1

Baseline: 11.20 delivery at main commit `93804fbf9591b54d86fb170385491ed4ced024bd`. All existing delivery files are untouched. This is an additive research prototype, not a new production entry point.

## Audit and design

- `story_video_agent/phase5_pipeline.py:122-258` calls T01 recognition, comeback composer, comeback scope and delivery EDL generation. Do not replace that legacy path before regression.
- `story_video_agent_v3/story_first_hypotheses.py:111-124` already supports explicit story_anchor rows and uses goal_action only as a fallback.
- `story_video_agent_v3/story_first_revision.py:365-405` still assigns additions a fixed buildup_bridge_action role; later work must carry template-aware narrative intent.
- P3/P3.5 preview acceptance remains separate from demonstrated quality improvement. Do not treat additional footage or an accepted preview as a verified better story.

## Stage 1 implementation

External ordered slot graph, material inventory built from the native enriched event JSON and predicted V1-adapter causal document, ID-only planner request/response binding, explicit source-time windows and repeatable slots. Every material remains a hypothesis, not a verified match causal claim. The template is supplied, not inferred from a benchmark reference. The sample templates are illustrative public category-level designs, not annotations or validated model performance. No match-specific IDs, no model calls and no automatic template selection.

Three pilot types: repeated goalkeeper saves, set-piece breakthrough, alternating threats. Existing T01 remains on its delivery path. A generic custom template may be passed instead. Missing evidence produces missing_required_slots, never fabricated nodes. No model-supplied timestamps are used. Replay/slow-motion overlap is screened against input metadata; this is not independent first-live verification.

Example from repo root (paths are placeholders, use a single native source and measured duration):

```bash
python research/sportscausal/template_graph.py \
  --template research/sportscausal/templates/keeper_rescue.json \
  --events /path/to/01_enrich/events_enriched.json \
  --predicted-causal /path/to/03_v1_adapt/predicted_causal.json \
  --video-id SOURCE_ID --duration-sec 7200 \
  --out-dir /path/to/new_request_dir

# Supply a planner-produced JSON file, with only bindings, in a new output dir:
# {"bindings":[{"slot_id":"save","material_ids":["event:actual_id_1","chain:actual_id_2"]}]}
# Same command plus --selection /path/to/selection.json and a fresh --out-dir.

cd research/sportscausal
python -m unittest -v test_template_graph.py
```

Outputs: inventory.json, planner_request.json, optional story_graph_bundle.json and candidate_edl.json. The candidate EDL carries story_anchor and source/event/chain bindings in the shape used by Story-First. Full legacy rendering compatibility and generic reflection have NOT been tested or established.

## Next stage and limits

1. Cursor runs synthetic regression and a zero-HTTP dry run on permitted enriched events/predicted chains from existing cases; no reference chains fed to the planner. Then run a real planner on a non-T01 case and inspect graph/EDL.
2. Existing template uses ordered slots; nonchronological editing and multi-source story assembly are not supported in this stage. Slot cardinality is structural, not semantic. Same goalkeeper/team, valid alternation, correct set-piece linkage, narrative contribution and first-live are not proven by ID binding. Review video before accepting.
3. Integrate a generic planner into the research entry point, then adapt renderer and Story-First revision roles. Preserve T01 as no-regression baseline and use FanEdit Eval v2 externally, never as a planner oracle. No change to the delivery path, scorer activation or paid experiments in this commit.
