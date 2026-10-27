"""乌龙球词表 + own_goal_causal_chain 规则识别。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ALGO = ROOT / "algo"
if str(ALGO) not in sys.path:
    sys.path.insert(0, str(ALGO))

from causal_chain2.chain_schema import EVENT_TYPES  # noqa: E402
from causal_chain8.mapping.presets import (  # noqa: E402
    EN_EVENT_TO_TYPE,
    ZH_EVENT_TO_TYPE,
    map_event_strict,
)
from causal_chain8.rules.rank import (  # noqa: E402
    infer_category_from_events,
    rule_top1,
)
from api.adapters import map_event_type  # noqa: E402


def test_event_vocab_has_own_goal():
    assert EVENT_TYPES.get("own_goal") == "乌龙球"
    assert ZH_EVENT_TO_TYPE.get("乌龙球") == "own_goal"
    assert EN_EVENT_TO_TYPE.get("own_goal") == "own_goal"


def test_map_chinese_and_en_own_goal():
    w: list = []
    assert map_event_strict({"type": "乌龙球"}, w) == "own_goal"
    assert map_event_strict({"type": "", "type_en": "Own_goal"}, w) == "own_goal"
    assert map_event_type("own_goal", "乌龙球") == "own_goal"
    assert map_event_type("乌龙球", None) == "own_goal"


@pytest.mark.parametrize(
    "types",
    [
        ["throw_in", "pass", "pass", "shot", "own_goal"],
        ["corner", "own_goal"],
        ["assist", "dribble_past", "shot", "keeper_save", "own_goal"],
        ["cross", "header_shot", "own_goal"],
    ],
)
def test_own_goal_terminal_classifies_own_goal_chain(types):
    assert rule_top1(types, profile={}) == "own_goal_causal_chain"
    assert infer_category_from_events(types) == "special"


@pytest.mark.parametrize(
    "types",
    [
        ["pass", "shot", "goal"],
        ["shot", "goal"],
        ["cross", "header_shot", "goal"],
    ],
)
def test_plain_goal_not_forced_to_own_goal_chain(types):
    assert rule_top1(types, profile={}) != "own_goal_causal_chain"
