# V3-R-General R2a.3 — relation graph preflight

Baseline artifacts: 3d90a20fe7970df903cda9fb76d589765ca94664 (R2a.2 code c698ad6).
GitHub partial head: 98d1fb1822ccde6b60a1f98dfa78bc50f1e8aa25. This overlay completes
that head; only the research directory is touched. Do not overwrite an independently
modified version of these files. No existing R1.1/R2a.2 algorithms or artifacts are changed.

## Implementation

- `episode_goal_binding.py`: consumes existing V3-R score_path, explicit source and
  scoreboard-side mapping. Reuses the historical 180s before/15s after goal search
  bounds. Only unique, noncrossing compatible LIVE Goal annotations are bound;
  scoreboard confirmation is not action localization or clip timing.
- `episode_relation_evidence.py`: original adjacent chain member pairs, independently
  stated possession actors and explicit recovery references; two conditional team
  assignments retained for both-missing Shot/Save. A defensive action can break
  continuity; a save need not transfer possession. No generic nearest-team inference.
- `event_relation_graph.py`: local shot/save, delivery/keeper, keeper deflection/follow-up,
  shot/goal edges. Chain subtype is not an exclusive whitelist. A compatible local
  raw pair is also available to the no-chain baseline. Missing-role propagation
  requires actual chain support; a third explicit keeper/recovery reference may
  resolve both missing roles. Score-bound goals can support an adjacent empty shot
  when original predicted membership supports the relation. All inferred facts
  remain separate from the original input. Same-attack connected paths, not broad
  predicted windows. Conflicting overlapping edge proposals are not merged.
- `r2a3_patterns.py`: graph-to-episode projections with common component identity
  across attack/rescue views. Uses existing Repeat/Alternate. Keeps union of media
  windows, flags overlapping distinct paths. Three arms: full; without chains
  (same score input); without score (same chain input). Reuses persisted R1.1
  normalized_semantics.json, not the old normalization run.
- `test_event_relation_graph.py`: 14 synthetic cases. Local py_compile is not a
  passing server unit-test run. Run actual regression and new tests on server.

## Server procedure

From a clean independent research worktree at the above partial head, extract the
zip at repository root. Inspect `git diff --stat` and `git status --short`. Only the
six overlay files under research/sportscausal should be added/modified. Run:

```
cd research/sportscausal
python -m unittest -v test_v3r_general test_causal_episodes test_event_relation_graph
```

Use original complete Stage 1.2 evidence.json and persisted R2a.2 normalized semantics
for each match. Reuse the existing frozen V3-R score path, not a newly generated
score trajectory. Wrap it in a source-bound JSON of this form (illustrative only):

```
{
  "video_id": "exact Stage 1.2 evidence video_id",
  "score_side_mapping": {"left": "team_1", "right": "team_2"},
  "score_path": [ ... original V3-R rows unchanged ... ]
}
```

The mapping shown is only an example; verify the actual scoreboard left/right
and team metadata for A/B; do not assume this mapping or infer it from gold story
labels. Retain the original score file and its hash in the report. If no usable
existing path is available, report the blocker and do not fabricate one.

```
python r2a3_patterns.py --evidence A_EVIDENCE_JSON \
  --semantics artifacts/v3r_general_r2a2_preflight/A/normalized_semantics.json \
  --score-path A_SCORE_PATH_JSON --allow-dev \
  --out-dir artifacts/v3r_general_r2a3_preflight/A
python r2a3_patterns.py --evidence B_EVIDENCE_JSON \
  --semantics artifacts/v3r_general_r2a2_preflight/B/normalized_semantics.json \
  --score-path B_SCORE_PATH_JSON --allow-dev \
  --out-dir artifacts/v3r_general_r2a3_preflight/B
```

Return full test stdout, summary.json, relation_graph.json / causal_episodes.json /
keeper_rescue.json / alternating_threats.json from each arm, both diff files, and
REPORT.md. Report source commit and checksums. Audit all inferred roles and all
new typed edges against original notes/attrs/member order; compare with saved
3d90a20 (do not rerun it). Focus A416→417, A476→477, B259→260 dual views;
A398→399→400 and B586→587 continuation; A640→641; every newly score-bound Goal
and any shot inferred from it; both-unknown Save/Shot context options and whether
there is actual explicit cross-reference; B625 conflict retained; actor conflicts;
possible duplicate episodes. Distinguish gains present even without chains from
chain-specific gains and score-specific gains. Check projection event IDs and
media segments, not only count changes. Preserve all previous artifacts. No
LLM/VLM, render, benchmark labels, manual edits or old experiment re-execution.

## Limitations

Local 5s action interval, 15s context neighborhood and historical score-search
bounds are uncalibrated priors. The code is a bounded relation-graph method, not
full ball-possession state reconstruction or a general global constraint solver.
A common predicted chain is still only an uncertain relation hypothesis. Both-role
missing pairs with ambiguous possession remain conditional alternatives. A direct
score observation cannot substitute for actual annotated goal action. The method
can still miss densely spaced or ambiguously annotated goals; own goals and score
corrections are not handled by this stage. Overlapping distinct paths require
review, not arbitrary merge. No multi-phase narrative segmentation, causal truth,
first-live verification, story quality, EDL or formal FanEdit performance claims.
