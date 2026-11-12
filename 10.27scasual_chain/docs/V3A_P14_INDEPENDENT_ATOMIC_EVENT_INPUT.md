# P14 — Restore atomic-event enrichment as a legitimate input modality

Base: P13 server report commit `fc89d90d9003458f4d31619227526d0178d14875`.
Branch: `story-va-v3a-p14-independent-atomic-events`.

## Corrected input protocol

Event annotations and causal-chain gold are different things.
The existing `atomic_event_enrich.py` previously extracted atomic Goal
events from human `causal_chains` and therefore rightly excluded that
specific path from raw-only evaluation. **Do not discard the whole
enrichment module.** P14 adds an independent, event-level JSON input,
`--independent-atoms-json`, that contains only `atomic_events`.

Example (synthetic schema example; not an A-match label):
```json
{
  "atomic_events": [
    {"event_id": "independent_001", "event_type": "Goal",
     "t_ms": 120000, "broadcast_phase": "UNKNOWN"}
  ]
}
```
`t_ms` is original-source media time in milliseconds. `broadcast_phase`
is `LIVE`, `REPLAY`, or `UNKNOWN`. The label is an *annotation*, not
automatic proof of first-LIVE. No causal chain IDs, graph edges, story
roles, chain subtype, EDL or source-video gold from evaluation targets.

The independent atom path is different from legacy `--causal-json`:
- `RAW_EVENTS_ONLY`: MP4 + original events; no external event annotations.
- `INDEPENDENT_ATOMIC_ANNOTATED`: MP4 + original events + independent
  event annotations; a separately reported event-annotated evaluation.
- `HUMAN_ATOM_ENRICHED_DEV`: historical extraction from human causal
  chains; development reproduction only, **not** a fair causal/story
  prediction evaluation.

No evaluation may claim a missing Goal was *detected* by the Agent if
its timestamp was already supplied as an input annotation. Report
event-recovery and conditional causal/story generation separately.

## Reused pipeline

`enrich_files` merges independent event atoms and deduplicates;
`closed_loop_cli.run_match` continues 8.31 strip prediction and
Goal Recovery; `goal_recovery.attach_independent_goal_atoms` binds
a unique annotated Goal inside the corresponding score transition
bracket as `annotated_goal_action_unverified_video`. Ambiguous
multiple candidates are unresolved. This is an *annotated action
hypothesis*; first-LIVE video verification and delivery gates remain.

`story_e2e_agent.resolve_baseline` and `story_full_e2e_cli` now
carry the independent annotation input through the same fresh V3-R
and V3-A chain. The original raw-only mode is preserved, not overwritten.

## Cursor verification — no paid API

```bash
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_p14_independent_atomic_annotations.py \
  tests/test_v3a_p13_reuse_goal_localizer_and_semantic_gate.py \
  tests/test_v3a_p12_goal_evidence_recall.py \
  tests/test_v3a_p11_raw_input_and_critic_coverage.py
```

First validate using a **real independently annotated atomic event
file** that was created without reading human causal/story chain
annotations. Verify its provenance and source-video PTS coordinate
system. Do not extract that file from `*_causal.json` and then call
it independent. Do not copy P10-F sealed or test-set Gold timestamps.

Then run fresh E2E in a new output directory:
```bash
PYTHONPATH=algo python -m story_video_agent_v3.story_full_e2e_cli \
  --source-mp4 "$SOURCE" --events-json "$EVENTS" \
  --independent-atoms-json "$INDEPENDENT_ATOMS" \
  --out-dir "$NEW_OUTPUT_DIR" --max-rounds 1 --no-smoke-render
```

Do **not** use `--strict-raw-only` for this mode: it explicitly
means *no extra event annotations*. No `--causal-json`, no Phase5
reuse, no paid API, no fake VLM outputs. If no genuine independent
event-level annotation file is available, **do not fabricate one**;
run only the unit tests and report the missing data prerequisite.

Return: source SHA, input schema and provenance; counts of raw,
injected, deduplicated events; Goal Recovery candidate-to-atom
binding and verification status; 8.31 chain counts; V1 goal terminals;
Phase5 Graph and EDL; actual video segments; first-LIVE status;
release status; and whether narrative quality is *verified* or not.

## End goals

1. Generic across-match and across-story-template end-to-end Video
Story Agent, including accurate goal and event evidence, coherent
setup/turning-point/ending and meaningful Critic/Planner/Verifier
revision, not merely gate checking.
2. Unified ACL paper: independently annotated event and short-chain
benchmark + new long-story benchmark (~half), complete E2E Agent
(~half). Report event-annotated vs raw/noisy-event conditions without
mixing the metrics or using target chain labels as inputs.

Status: **ZERO-PAID SERVER VERIFY ON **. Documented suite 28 passed / 1 failed (P11 strict-reject token rename). **No genuine independent atomic annotation file found** on server; E2E with  not run (no fabrication / no causal extract). See .
