"""causal_chain6 模版表（基于业务骨架，独立于 chain2）。"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Tuple

from causal_chain6.schema.skeletons import (
    CHAIN4_SKELETONS,
    all_chain4_template_ids,
    skeleton_as_templates,
)

CHAIN4_TEMPLATES: Dict[str, Dict[str, Any]] = skeleton_as_templates()
ALL_TEMPLATE_IDS: Tuple[str, ...] = tuple(all_chain4_template_ids())


def get_chain_templates(overrides: Dict[str, Dict[str, Any]] | None = None) -> Dict[str, Dict[str, Any]]:
    out = copy.deepcopy(CHAIN4_TEMPLATES)
    for tid, patch in (overrides or {}).items():
        if tid not in out:
            out[tid] = dict(patch)
        elif isinstance(patch, dict):
            out[tid].update(patch)
    return out


def template_label_zh(template_id: str, templates: Dict[str, Dict[str, Any]] | None = None) -> str:
    meta = (templates or CHAIN4_TEMPLATES).get(template_id, {})
    return str(meta.get("label_zh", template_id))


def templates_in_category(category: str) -> List[str]:
    return [tid for tid, meta in CHAIN4_TEMPLATES.items() if meta.get("category") == category]


def all_template_ids() -> Tuple[str, ...]:
    return ALL_TEMPLATE_IDS


def get_skeleton(template_id: str) -> Dict[str, Any]:
    return dict(CHAIN4_SKELETONS.get(template_id, {}))
