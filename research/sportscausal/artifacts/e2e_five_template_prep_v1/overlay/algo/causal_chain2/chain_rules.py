"""链模板典型骨架与转移规则（自包含，供分类 prompt 与评测过滤）。"""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from causal_chain2.chain_schema import ALL_TEMPLATE_IDS

CANONICAL_SEQUENCES: Dict[str, List[List[str]]] = {
    "corner_cross_goal": [
        ["throw_in", "corner", "cross", "header_shot", "goal"],
        ["corner", "cross", "header_goal"],
        ["corner", "pass", "cross", "shot", "goal"],
    ],
    "rebound_follow_up_goal": [
        ["shot", "keeper_save", "shot", "goal"],
        ["cross", "shot", "keeper_save", "shot", "goal"],
    ],
    "turnover_counter_goal": [
        ["successful_tackle", "pass", "dribble_past", "shot", "goal"],
        ["interception", "pass", "cross", "goal"],
        ["possession_lost", "successful_tackle", "shot", "goal"],
    ],
    "penalty_scored_chain": [
        ["foul", "var", "penalty", "goal"],
        ["foul", "penalty", "goal"],
    ],
    "red_card_decision_chain": [
        ["foul", "controversy", "var", "red_card"],
        ["foul", "yellow_card", "foul", "second_yellow_red"],
    ],
    "outcome_other": [
        ["pass", "shot", "goal"],
        ["dribble_breakthrough", "shot", "goal"],
    ],
    "goal_disallowed_chain": [
        ["goal", "controversy", "var", "disallowed_goal"],
        ["shot", "goal", "var", "disallowed_goal"],
    ],
    "var_penalty_cancelled_chain": [
        ["foul", "var", "penalty", "var", "free_kick"],
        ["penalty", "var", "free_kick"],
    ],
    "var_overturn_chain": [
        ["goal", "var", "disallowed_goal"],
        ["foul", "var", "offside"],
    ],
    "shot_save_chain": [
        ["pass", "shot", "keeper_save"],
        ["cross", "header_shot", "keeper_save"],
    ],
    "shot_post_bar_chain": [
        ["shot", "shot"],
        ["free_kick", "shot", "shot"],
    ],
    "second_phase_after_frame_chain": [
        ["shot", "shot", "corner"],
        ["cross", "shot", "shot", "cross"],
    ],
    "goal_line_extreme_save_chain": [
        ["shot", "goal_line_clearance"],
        ["corner", "header_shot", "goal_line_clearance"],
    ],
    "throw_in_build_up_chain": [
        ["throw_in", "pass", "cross", "shot"],
        ["throw_in", "dribble_past", "foul"],
    ],
    "own_goal_causal_chain": [
        ["cross", "header_shot", "own_goal"],
        ["possession_lost", "shot", "own_goal"],
        ["cross", "shot", "own_goal"],
        ["pass", "cross", "own_goal"],
        ["shot", "own_goal"],
        ["corner", "own_goal"],
        ["throw_in", "pass", "pass", "shot", "own_goal"],
    ],
    "keeper_spill_danger_chain": [
        ["shot", "keeper_save", "shot"],
        ["cross", "header_shot", "keeper_save", "shot"],
    ],
    "deflection_goal_chain": [
        ["shot", "goal"],
        ["cross", "shot", "goal"],
    ],
    "quick_restart_set_piece_chain": [
        ["free_kick", "pass", "shot"],
        ["throw_in", "pass", "cross"],
    ],
}


def transitions_from_sequences(seqs: List[List[str]]) -> Set[Tuple[str, str]]:
    out: Set[Tuple[str, str]] = set()
    for seq in seqs:
        for a, b in zip(seq, seq[1:]):
            out.add((a, b))
    return out


ALLOWED_TRANSITIONS: Dict[str, Set[Tuple[str, str]]] = {
    tid: transitions_from_sequences(CANONICAL_SEQUENCES[tid])
    for tid in ALL_TEMPLATE_IDS
}


def sequence_matches_template(template_id: str, event_types: List[str]) -> bool:
    if template_id not in CANONICAL_SEQUENCES:
        return False
    return event_types in CANONICAL_SEQUENCES[template_id]


def consecutive_pairs_allowed(template_id: str, event_types: List[str]) -> bool:
    if template_id not in ALLOWED_TRANSITIONS:
        return False
    allowed = ALLOWED_TRANSITIONS[template_id]
    return all((a, b) in allowed for a, b in zip(event_types, event_types[1:]))
