# SportsCausal Stage 1.2 evidence preflight

- Code: `1c46b11`
- Unittest `test_evidence_representation.py`: **6/6 OK**
- Paid API / render / predicted-chain regen / algo edits: **no**

## Default mode rejects A/B historical atom_fill
Both matches require `--allow-dev` (HUMAN_ATOM_ENRICHED_DEV). See `default_reject.json`.

## A_uae_oman
- input_tier: `HUMAN_ATOM_ENRICHED_DEV`
- atoms/planner events: 663 / 663
- notes/attributes/types/teams preserved: True/True/True/True
- chain states: {'FULL': 9, 'PARTIAL': 64, 'NONLIVE_CHAIN': 8}
- planner chain availabilities (FULL/PARTIAL only): {'FULL': 9, 'PARTIAL': 64}
- no replay in planner / no NONLIVE|UNAVAILABLE in planner: True / True
- PARTIAL context retained: True (64 chains)
- planner compact chars old→new: 398088 → 367160 (reduction 0.0777)
- overlap/disjoint demos: {'overlap_merge': {'event_ids': ['event_000004', 'event_000005'], 'input_windows': [[643.16, 661.85], [643.16, 661.85]], 'merged_groups': [[643.16, 661.85, ['event_000004', 'event_000005']]], 'n_segments': 1, 'pass_single_union_segment': True}, 'disjoint_retain': {'event_ids': ['event_000014', 'event_000015'], 'input_windows': [[662.22, 676.14], [696.18, 706.86]], 'merged_groups': [[662.22, 676.14, ['event_000014']], [696.18, 706.86, ['event_000015']]], 'n_segments': 2, 'pass_two_segments_no_gap_fill': True}}
- partial citation demo pass: True

## B_osasuna_celta
- input_tier: `HUMAN_ATOM_ENRICHED_DEV`
- atoms/planner events: 660 / 660
- notes/attributes/types/teams preserved: True/True/True/True
- chain states: {'FULL': 18, 'PARTIAL': 51, 'NONLIVE_CHAIN': 4}
- planner chain availabilities (FULL/PARTIAL only): {'FULL': 18, 'PARTIAL': 51}
- no replay in planner / no NONLIVE|UNAVAILABLE in planner: True / True
- PARTIAL context retained: True (51 chains)
- planner compact chars old→new: 400397 → 364857 (reduction 0.0888)
- overlap/disjoint demos: {'overlap_merge': {'event_ids': ['event_000004', 'event_000005'], 'input_windows': [[422.04, 432.83], [422.04, 432.83]], 'merged_groups': [[422.04, 432.83, ['event_000004', 'event_000005']]], 'n_segments': 1, 'pass_single_union_segment': True}, 'disjoint_retain': {'event_ids': ['event_000010', 'event_000011'], 'input_windows': [[433.28, 443.57], [458.08, 468.25]], 'merged_groups': [[433.28, 443.57, ['event_000010']], [458.08, 468.25, ['event_000011']]], 'n_segments': 2, 'pass_two_segments_no_gap_fill': True}}
- partial citation demo pass: True

## Samples
Real Save / Shot / set-piece-like planner rows + touching predicted chains: `samples/planner_event_chain_examples.json`.

## Outputs
`{A,B}/{keeper_rescue,set_piece_breakthrough,alternating_threats}/{evidence,planner_request}.json`

