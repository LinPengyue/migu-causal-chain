# FanEdit evaluation protocol v2

Data frozen at `e67d7c9f596db5b3cd5618f4692733126e68b1c1`, `../v1.1/`. No annotation, original ZIP, or v1.1 checksum changes. FanEdit is the benchmark; SportsCausal is the story agent; Template + LLM is a causal baseline, not a separate proposed method.

## Run

Python 3.9+; standard library only. Run from the repository root:

```bash
python benchmark/fanedit/eval_v2/evaluate.py --task causal --pred causal_predictions.jsonl --out causal_scores.json
python benchmark/fanedit/eval_v2/evaluate.py --task story --pred story_predictions.jsonl --out story_scores.json
python benchmark/fanedit/eval_v2/selftest.py
```

Default thresholds: 0.3, 0.5, 0.7; one prediction file, no repeated inference. Override with `--thresholds 0.3 0.5 0.7` or legacy `--tiou 0.5`. Prediction JSONL schema is unchanged from v1.1; all event IDs must refer to the correct source and overlap the segment in media time. Repeated event IDs are treated as a set (60 causal references contain repeats). Each annotated segment remains an instance for segment matching, even if intervals coincide. Causal eligibility uses the explicit causal_eval_source flag, including eligible sources with no positive reference. `--exclude-known-dev` excludes four known development matches; the remaining 80 are exposure-unverified, not a certified held-out split.

## Table 2: FanEdit-Causal

For each threshold t, a TP requires same match, category and subtype, same-source temporal IoU >= t, and event-set F1 >= 0.5 (configurable with --event-threshold; 0.5 is the proposed protocol default). Maximum-cardinality one-to-one assignment, breaking ties by total IoU. Precision = TP / all predictions; Recall = TP / all references; F1 = 2 TP / (all predictions + all references). Macro-F1 averages over subtype pairs present in reference or prediction; classes absent from both are excluded. All thresholds use the same event threshold. Event-set matching does not assess event order or semantic causal validity.

Read `by_threshold["0.5"]` for the main table; all three thresholds for sensitivity analysis.

## Table 1: FanEdit-Story

A story is a typed instance with an ordered list of source-video segments. Temporal IoU is intersection over union of merged selected intervals, independently per video_id, summed across sources. No full-match offset or enclosing interval is invented.

- Story association: same match and category/subtype; maximum-weight one-to-one assignment by story union IoU, with zero-IoU edges discarded. This association is fixed across thresholds for segment F1, mIoU and Event F1.
- F1@t: within each associated story pair, one-to-one maximum-cardinality segment matching at segment IoU >= t. Micro F1 = 2 matched segments / (all predicted segments + all reference segments), including segments in unmatched stories.
- R@t: story-level recall, maximum-cardinality typed story matching at union IoU >= t, divided by all reference stories. This matching is computed separately at each threshold; it need not be the fixed soft-metric assignment. This preserves monotonic recall across thresholds.
- mIoU: sum of union IoUs over the fixed association / max(total predicted stories, total reference stories). Unmatched stories contribute zero. This is a FanEdit adaptation for multiple stories per match, not the original single-query MEDit-Bench formula.
- Event F1: for each fixed story pair compute 2 |predicted event IDs intersect reference event IDs| / (|predicted IDs| + |reference IDs|); aggregate as 2 times the sum of pair F1 / (total predicted stories + total reference stories). Unmatched stories contribute zero. Repeated IDs do not increase credit.

Read `by_threshold["0.5"].segment.f1`, `miou`, `by_threshold["0.5"].story_recall`, `event_f1` for the main table; report segment F1 and story recall at 0.3/0.5/0.7 in the sensitivity table. Scores are fractions, not percentages.

## Efficiency

Optional `--run-log run_log.jsonl`, one row per evaluated match:
```json
{"match_id":"<actual match ID>","elapsed_sec":120.0,"api_cost_usd":0.12}
```
Use actual wall-clock task time and actual API cost, including retries and failed/empty predictions; story end-to-end cost must include the causal upstream if run as part of the task. Average minutes and USD per match are returned only when all selected matches have valid logs. Missing or incomplete logs return null, never zero. Log example values are illustrative only.

## Limitations

Provisional non-exhaustive references; unannotated valid stories can be counted as unmatched. Automatic scores measure reference agreement, not causal correctness, narrative quality, first-live verification, or final rendered-video quality. Those require separate human/video assessment. Story F1 measures selection, not order. Direct-video baselines need a common event-ID grounding adapter to use the existing schema fairly; it must not read reference chains. No model inference or API cost is incurred by this evaluator. Self-test is not a model result.
