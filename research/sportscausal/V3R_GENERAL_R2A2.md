# V3-R-General R1.1 / R2a.1 / R2a.2

Baseline: 40c8db4219f72812f4f835a3467498f4df70ceab (R1/R2a preflight at 4a9857a).
All work is in research/sportscausal; historical matcher and artifacts remain unchanged.
No model calls or render.

## Implementation

- episode_semantics.py: same-note coordinated shot clauses; separate action/attempt
  from save/threat evidence. Ordinary catches and clearances stay in the semantic pool.
  A successful save annotation is a rescue proxy, not proof of a high-value highlight.
- causal_episodes.py: find local pairs in predicted shot_save_chain or
  goal_line_extreme_save_chain members. Require adjacent original member IDs and
  global eligible-atom adjacency, positive bounded time separation (default 5s),
  compatible action types and opposing actor roles. For PARTIAL only use actually
  present adjacent members, never complete missing actions or the full predicted chain.
  The default is an uncalibrated local time prior, not a learned threshold.
  One-hop team inference is allowed only for a missing role with empty notes/attributes;
  preserve conflicts, no player inference, no propagation if both roles are absent.
  Duplicate supporting chains do not duplicate the pair. No cross-pair transitive closure.
  Independent annotations remain available without a chain. Distinct media windows are
  preserved as a union, not gap-filled. Ordinary delivery/catch linkage alone does not
  prove a threatening chance. Keep rejection evidence for review.
- episode_patterns.py: repeat/alternate consume episode projections rather than raw
  event rows; one candidate per actor for repeat and whole-match runs for alternate.
  Same-actor overlapping unlinked windows are still a proxy; overlapping linked and
  unlinked windows or multiple independent links require later dedup review.
  Cross-actor window overlap is a diagnostic; tied action times are not counted as
  ordered alternation. No claim of possession segmentation, dominance, narrative
  quality, first-live or final EDL.
- test_causal_episodes.py: synthetic positive/negative checks including a case where
  the chain changes both role binding and candidate existence.

## Required A/B validation (Cursor)

Use the original Stage 1.2 full evidence.json files, not compact planner messages,
since PARTIAL compact tables lose missing original member positions.
Do not recreate input data, use gold story/chain labels, call APIs, or render.
Run the current regression suite once and run the new paired ablation once per match:

    cd research/sportscausal
    python -m unittest -v test_v3r_general test_causal_episodes
    python episode_patterns.py --evidence A_EVIDENCE_JSON --allow-dev --out-dir artifacts/v3r_general_r2a2_preflight/A
    python episode_patterns.py --evidence B_EVIDENCE_JSON --allow-dev --out-dir artifacts/v3r_general_r2a2_preflight/B

Review outputs:
- normalized_semantics.json: distinguish direct claims from episode inference.
- with_chains/causal_episodes.json and without_chains/causal_episodes.json
- both modes' keeper_rescue.json and alternating_threats.json
- ablation_diff.json and summary.json
- REPORT.md: source commit, exact commands, test stdout and HTTP count;
  audit EVERY accepted link and inferred role, including original chain member order,
  notes/attrs, action gap and any contradictory/duplicate evidence. Review all
  rejected pairs and both-unknown shot/save cases; do not infer a side from the
  predicted subtype alone. Compare A374/B615 shooter recovery, A282/417/641
  retained role binding, B625 conflict, and ordinary catches/clearances.
  Compare baseline 40c8db4 results using saved outputs, not another baseline run.
  Report changes in actual event membership, actor sequence, and evidence segments,
  not merely count differences. If there is no useful gain or new false positives,
  explicitly say so. No manual candidate edits.
  Inspect same-side linked/unlinked window overlaps, long gaps and phase coherence.
  Counts are not benchmark precision/recall, since A/B use HUMAN_ATOM_ENRICHED_DEV.

## Remaining limitations

Only local shot/save or delivery/keeper relations are implemented. Many actual
predictions are broad PARTIAL windows with multiple possessions, so validated local
links may be sparse. Both roles missing cannot be resolved by this first method;
context-based actor inference needs separate evidence and evaluation. No general
possession reconstruction, no same-actor phase segmentation, no multiple alternating
substories, no criticality ranking or narrative bridge selection. Existing R2b
state/path code is not evaluated here. Do not move to R3/R5 until this audit.
