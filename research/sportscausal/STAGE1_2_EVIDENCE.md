# Stage 1.2 Evidence Representation

Based on Stage 1.1 audit 06d8643. Additive research-only module; legacy Stage 1 and delivery untouched.

- Preserve original notes, attributes, type, time, scores and team header; compact column-oriented event representation. Full eligible event inventory, no type-only candidate pruning.
- Predicted chains are context, not executable clips. FULL/PARTIAL/UNAVAILABLE/NONLIVE_CHAIN describes evidence availability only; keep partial context with explicit missing count. No nonlive chain context in planner request.
- Select event IDs for each story instance and optional intersecting predicted chain IDs. Union overlapping event windows inside an instance; retain separate windows for disjoint actions. No full chain envelope, no model timestamps, no claim of first-live or semantic quality.
- Historical A/B enrich reports and causal_atom_fill provenance force HUMAN_ATOM_ENRICHED_DEV. Explicit --allow-dev required. Removing filled IDs after predicting does not establish clean inference. The input tier is not a guarantee of upstream prediction lineage; verify actual run manifests in formal evaluation.
- Existing source replay overlap screening remains conservative. Unknown broadcast phase is not proof of live. Notes and attributes are input claims, not independent video verification. No automated same-team inference. No model calls in this stage.

From research/sportscausal:
```bash
python -m unittest -v test_evidence_representation.py
python evidence_representation.py --template templates/keeper_rescue.json \
  --events /actual/events_enriched.json --predicted-causal /actual/predicted_causal.json \
  --enrich-report /actual/enrich_report.json --video-id SOURCE_ID \
  --duration-sec MEASURED_DURATION --allow-dev --out-dir /new/output
```

Optional --selection JSON with bindings:[{slot_id,instances:[{event_ids,chain_ids}]}] creates candidate graph and EDL. No renderer or existing reflection integration yet.

Preflight on A/B: compare compact JSON characters against v1 with the same serializer, report event count, chain status/type counts, notes/attribute retention, team header and actual Save examples. Assert default rejects both historical inputs; allow-dev enables diagnostics. Check source windows, overlap merge, disjoint intervals, partial chain citation, and no replay event or nonlive chain in planner. No need to rerun prior tests or regenerate comeback videos. New tests supplied, not executed by author.
