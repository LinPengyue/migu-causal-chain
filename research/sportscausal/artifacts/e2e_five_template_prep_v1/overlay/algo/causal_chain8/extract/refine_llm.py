"""可选 LLM 精修：从候选 indices 中选 event_id 子集。"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from causal_chain2.llm_json import extract_json_object
from causal_chain2.llm_qwen import generate_text

from causal_chain8.extract.align import AlignmentCandidate
from causal_chain8.llm.constants import SYSTEM_AGENT_V4


def refine_extraction_llm(
    events: List[Dict[str, Any]],
    candidates: List[tuple[float, AlignmentCandidate]],
    *,
    model,
    processor,
    device: str,
    max_new_tokens: int = 384,
) -> Optional[List[int]]:
    if not candidates or model is None or processor is None:
        return None

    compact = [
        {
            "index": i,
            "event_id": e.get("event_id", ""),
            "type": e.get("type"),
            "t_ms": e.get("t_ms"),
        }
        for i, e in enumerate(events)
    ]
    top = candidates[:3]
    cand_txt = "\n".join(
        f"- {c.template_id} score={s:.3f} indices={c.indices} pattern={' → '.join(c.pattern)}"
        for s, c in top
    )
    prompt = f"""## 任务
从下列事件列表中，选出构成**一条足球因果链**的最小子序列（按时间顺序）。
输出所选事件的 index 列表（整数，升序）。

## 规则候选
{cand_txt}

## 事件列表
{json.dumps(compact, ensure_ascii=False, indent=2)}

## 输出
{{"selected_indices":[0,1,2],"rationale":"一句话"}}
只输出 JSON。"""

    raw = generate_text(
        model,
        processor,
        SYSTEM_AGENT_V4,
        prompt,
        device,
        max_new_tokens=max_new_tokens,
        do_sample=False,
    )
    obj = extract_json_object(raw)
    if not obj:
        return None
    indices = obj.get("selected_indices")
    if not isinstance(indices, list):
        return None
    out: List[int] = []
    for x in indices:
        try:
            i = int(x)
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(events):
            out.append(i)
    return sorted(dict.fromkeys(out)) if out else None
