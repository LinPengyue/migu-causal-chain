"""逆风翻盘端到端：原始时间序列 → 识别 → 故事链 / 候选。

识别两层：story 出完整故事链；candidate 只凭比分翻盘出候选链；none 停止。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Union

from story_chain.comeback import build_match_story

ALGORITHM_ID = "t01_comeback_e2e"
PathLike = Union[str, Path]


def run(events_document: Dict[str, Any], causal_document: Dict[str, Any]) -> Dict[str, Any]:
    story = build_match_story(events_document, causal_document)
    story["algorithm"] = ALGORITHM_ID
    story["stages"] = ["recognize_timeline"]
    if story.get("has_story"):
        story["stages"].append("emit_story_chain")
    elif story.get("is_candidate"):
        story["stages"].append("emit_candidate_chain")
    else:
        story["stages"].append("stop")
    return story


def run_paths(events_path: PathLike, causal_path: PathLike) -> Dict[str, Any]:
    events_file = Path(events_path)
    causal_file = Path(causal_path)
    events_document = json.loads(events_file.read_text(encoding="utf-8"))
    causal_document = json.loads(causal_file.read_text(encoding="utf-8"))
    story = run(events_document, causal_document)
    story["events_file"] = events_file.name
    story["causal_file"] = causal_file.name
    return story
