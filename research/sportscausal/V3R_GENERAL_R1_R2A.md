# V3-R-General R1 / R2a (deterministic anchor discovery)

Preserve delivery and Stage 2 LLM baseline. New research-only prototype, no HTTP.
R1 consumes Stage 1.2 evidence, explicitly binds event actor roles from native
notes and role-specific attributes. Store source claims, team/player conflicts
separately; no neighboring-event identity inference. Team-level goalkeeper
candidates do not imply same named player. Current parser supports explicit
Chinese team-side and team-name forms and selected structured player references;
not all English aliases, synonyms, negation/passive patterns or free text are
covered. It is conservative heuristics, not a general semantic parser.

R2a supports two operators (repeat, alternate) via declarative patterns. Repeat
enumerates all actors with >= minimum distinct window groups; alternate compresses
consecutive same-side runs of observed shot/rescue threat proxies and requires >=3
runs. No ranking, no possession/dominance inference, no arbitrary cap on anchors.
Overlapping same-actor windows are grouped as a conservative episode proxy.
Predicted FULL/PARTIAL chain membership is retained as context, not causal proof.
No complete EDL yet; R3 assembly must handle overlapping cross-actor windows,
select context and distinct anchors, and avoid template-only edits. Score-state,
relation path and phase-change operators are planned, not implemented. T01
delivery stays unchanged.

Tests (new only):
    cd research/sportscausal
    python -m unittest -v test_v3r_general.py

Run both templates on existing Stage 1.2 A/B evidence:
    python temporal_patterns.py --evidence PATH/evidence.json \
      --template patterns/keeper_rescue.json --allow-dev --out-dir NEW_DIR

Use patterns/alternating_threats.json for alternating. Save actual semantic claims
and candidates plus a small manual annotation-grounded review (not video quality).
A/B are HUMAN_ATOM_ENRICHED_DEV; no benchmark performance claims. No rerun of
earlier paid planner or comeback. New tests supplied but not executed by author.
