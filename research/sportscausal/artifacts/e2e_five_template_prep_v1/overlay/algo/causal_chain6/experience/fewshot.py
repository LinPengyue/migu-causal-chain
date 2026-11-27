"""B：分层 few-shot。仅在规则分差偏低时注入，检索键为事件类型序列。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from causal_chain6.experience.noise import has_interference
from causal_chain6.rules.robust import denoise_types, normalize_types

_DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "exemplars.json"


def _lcs_len(a: Sequence[str], b: Sequence[str]) -> int:
    if not a or not b:
        return 0
    dp = [0] * (len(b) + 1)
    for x in a:
        prev = 0
        for j, y in enumerate(b, 1):
            cur = dp[j]
            dp[j] = prev + 1 if x == y else max(dp[j], dp[j - 1])
            prev = cur
    return dp[-1]


def _score(query: Sequence[str], cand: Sequence[str]) -> float:
    q = denoise_types(query, keep_foul=True)
    c = denoise_types(cand, keep_foul=True)
    if not q or not c:
        return 0.0
    lcs = _lcs_len(q, c)
    return lcs / max(len(q), len(c)) + (0.08 if has_interference(query) == has_interference(cand) else 0.0)


@lru_cache(maxsize=4)
def load_exemplars(path: str = "") -> List[Dict[str, Any]]:
    p = Path(path) if path else _DEFAULT_PATH
    if not p.is_file():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        items = raw.get("exemplars") or []
    else:
        items = raw
    return [x for x in items if isinstance(x, dict) and x.get("chain_template_id") and x.get("types")]


def retrieve_fewshot(
    query_types: Sequence[str],
    *,
    shortlist: Sequence[str],
    k: int = 3,
    path: str = "",
) -> List[Dict[str, Any]]:
    """按 shortlist 分层，每类最多 1 条，总分最高的 k 条。"""
    bank = load_exemplars(path)
    if not bank or k <= 0:
        return []
    q = normalize_types(query_types)
    allow = list(shortlist) or []
    picked: List[Dict[str, Any]] = []
    used_tid: set[str] = set()
    scored = []
    for ex in bank:
        tid = str(ex["chain_template_id"])
        if allow and tid not in allow:
            continue
        scored.append((_score(q, ex.get("types") or []), ex))
    scored.sort(key=lambda x: -x[0])
    picked_ids: set[int] = set()
    for sc, ex in scored:
        if sc <= 0.05:
            continue
        tid = str(ex["chain_template_id"])
        if tid in used_tid:
            continue
        picked.append(ex)
        used_tid.add(tid)
        picked_ids.add(id(ex))
        if len(picked) >= k:
            break
    if len(picked) < k:
        for sc, ex in scored:
            if id(ex) in picked_ids or sc <= 0.05:
                continue
            picked.append(ex)
            picked_ids.add(id(ex))
            if len(picked) >= k:
                break
    return picked[:k]


def format_fewshot_block(exemplars: List[Dict[str, Any]]) -> str:
    if not exemplars:
        return ""
    lines = ["## 形态示范（仅参考结构，不要照抄 annotation_id）"]
    for i, ex in enumerate(exemplars, 1):
        types = ex.get("types") or []
        chain = " → ".join(str(t) for t in types)
        src = ex.get("source", "jiaofu")
        lines.append(
            f"{i}. template={ex.get('chain_template_id')}  source={src}\n"
            f"   {chain}"
        )
    lines.append("若示范与当前终局冲突，以当前事件终局 + Tool 规则为准。")
    return "\n".join(lines)
