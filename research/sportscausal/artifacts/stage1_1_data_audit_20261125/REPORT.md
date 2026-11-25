# SportsCausal Stage 1.1 zero-cost data audit

- Paid API: **no**
- Algo changes: **no**
- Unit tests re-run: **no**
- Comeback reels regenerated: **no**

## 1. Provenance of atom_fill

For both A and B, `enrich_report.source_causal_atoms_only` points at delivery `*_causal.json` files that contain **human `causal_chains[]`** (with `chain_category` / `causal_chain_subtype`).
`atomic_event_enrich.extract_atomic_events` flattens those chain member events by `(type_en, t_ms)` and injects missing ones as `atom_fill_*` with `enrichment.provenance=causal_atom_fill`.
Chain labels are stripped on inject, but the **source of atoms is historical human causal-chain annotations**, not an independent atomic-event annotation file.
A separate API `enrich_with_independent_atoms` exists and forbids `causal_chains`; A/B closed-loop enrich did **not** use it.

### A_uae_oman
- raw events: 749; enriched: 879; atom_fill injected: 130
- human causal chains in `*_causal.json`: 25
- predicted chains: 81
- chain usability: available=9, partial_unusable=64, fully_unusable=8
- planner_request chars: 398088
- save neighborhood team-field hits: {'n_examples': 5, 'n_save_center_with_team_fields': 0, 'n_neighborhood_with_team_fields': 5}
- raw event player/team/jersey flags: {'has_player_fields_on_events': True, 'has_team_fields_on_events': True, 'has_jersey_or_color_on_events': False, 'example_types_found': {'Save': 2, 'Shot': 2, 'Corner_kick': 2, 'Goal': 1, 'Defensive_action': 2}}

### B_osasuna_celta
- raw events: 663; enriched: 834; atom_fill injected: 171
- human causal chains in `*_causal.json`: 33
- predicted chains: 73
- chain usability: available=18, partial_unusable=51, fully_unusable=4
- planner_request chars: 400397
- save neighborhood team-field hits: {'n_examples': 5, 'n_save_center_with_team_fields': 0, 'n_neighborhood_with_team_fields': 4}
- raw event player/team/jersey flags: {'has_player_fields_on_events': True, 'has_team_fields_on_events': True, 'has_jersey_or_color_on_events': False, 'example_types_found': {'Save': 2, 'Shot': 2, 'Corner_kick': 2, 'Goal': 2, 'Defensive_action': 2}}

## 2. Event attribute reality check
See `samples/event_fields_*.json` for real Save/Shot/Corner_kick/Goal/Defensive_action objects (not field-name-only).

## 3. Predicted short-chain audits
Per-chain rows in `chain_audits/predicted_chains_*.json` (category/subtype, span, valid/replay/unbound counts, exclusion reason, partial vs full unusable).

## 4. Planner request character costs
See `planner_char_cost_*.json` for per-field sums and lossless hoist/omit candidates.

## 5. Save neighborhoods / team attribution
See `samples/save_neighborhoods_*.json`. If `team_attribution_from_event_fields` is false, belonging cannot be decided from event attributes alone.

## GitHub
Committed on `research/sportscausal-template-generalization` for external GPT review.
