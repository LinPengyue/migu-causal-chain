"""因果逻辑完整率：主指标严格四条件；辅指标弱化。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple


def time_overlap(a0: int, a1: int, b0: int, b1: int) -> bool:
    return max(a0, b0) < min(a1, b1) or max(a0, b0) <= min(a1, b1)


def time_hit(
    gold: Dict[str, Any],
    pred: Dict[str, Any],
) -> bool:
    """时间条件：区间相交，或 gold 锚点落入 pred 窗（对齐短窗集锦）。"""
    g0, g1 = int(gold["t0_ms"]), int(gold["t1_ms"])
    p0, p1 = int(pred["t0_ms"]), int(pred["t1_ms"])
    if time_overlap(g0, g1, p0, p1):
        return True
    anchor = gold.get("anchor_t_ms")
    if anchor is None:
        # 回退：用 gold 窗中点
        anchor = (g0 + g1) // 2
    try:
        a = int(anchor)
    except (TypeError, ValueError):
        return False
    return p0 <= a <= p1


def time_iou(a0: int, a1: int, b0: int, b1: int) -> float:
    inter = max(0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    if union <= 0:
        return 1.0 if inter == 0 and a0 == b0 else 0.0
    return inter / union


def check_pair(gold: Dict[str, Any], pred: Dict[str, Any]) -> Dict[str, bool]:
    a = time_hit(gold, pred)
    b = (gold.get("chain_category") or "") == (pred.get("chain_category") or "")
    c = (gold.get("first_event") or "") == (pred.get("first_event") or "")
    d = (gold.get("last_event") or "") == (pred.get("last_event") or "")
    return {
        "a_time": a,
        "b_category": b,
        "c_first": c,
        "d_last": d,
        "strict": a and b and c and d,
        "aux_time_cat": a and b,
        "aux_time_cat_last": a and b and d,
    }


def match_golds_to_preds(
    golds: Sequence[Dict[str, Any]],
    preds: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """每条 gold 配一条最优 pred（一对一）：优先锚点落入窗，再比时间 IoU。"""
    used = set()
    rows = []

    def _score(g: Dict[str, Any], p: Dict[str, Any]) -> float:
        iou = time_iou(int(g["t0_ms"]), int(g["t1_ms"]), int(p["t0_ms"]), int(p["t1_ms"]))
        anchor = g.get("anchor_t_ms")
        if anchor is None:
            anchor = (int(g["t0_ms"]) + int(g["t1_ms"])) // 2
        try:
            a = int(anchor)
        except (TypeError, ValueError):
            a = (int(g["t0_ms"]) + int(g["t1_ms"])) // 2
        hit = 1.0 if int(p["t0_ms"]) <= a <= int(p["t1_ms"]) else 0.0
        return hit * 10.0 + iou

    for g in golds:
        # 保证 pairing 能读到 category/first/last 字段名
        g_norm = {
            "annotation_id": g.get("annotation_id"),
            "chain_category": g.get("chain_category") or g.get("category") or "",
            "first_event": g.get("first_event") or g.get("first") or "",
            "last_event": g.get("last_event") or g.get("last") or "",
            "t0_ms": g.get("t0_ms"),
            "t1_ms": g.get("t1_ms"),
            "anchor_t_ms": g.get("anchor_t_ms"),
        }
        best_i = None
        best_sc = -1.0
        for i, p in enumerate(preds):
            if i in used:
                continue
            sc = _score(g_norm, p)
            if sc > best_sc:
                best_sc = sc
                best_i = i
        if best_i is None or best_sc <= 0:
            rows.append(
                {
                    "annotation_id": g_norm.get("annotation_id"),
                    "matched": False,
                    "iou": 0.0,
                    "flags": {
                        "a_time": False,
                        "b_category": False,
                        "c_first": False,
                        "d_last": False,
                        "strict": False,
                        "aux_time_cat": False,
                        "aux_time_cat_last": False,
                    },
                    "gold": {
                        "category": g_norm["chain_category"],
                        "first": g_norm["first_event"],
                        "last": g_norm["last_event"],
                        "t0_ms": g_norm["t0_ms"],
                        "t1_ms": g_norm["t1_ms"],
                    },
                    "pred": None,
                }
            )
            continue
        p = preds[best_i]
        used.add(best_i)
        flags = check_pair(g_norm, p)
        rows.append(
            {
                "annotation_id": g_norm.get("annotation_id"),
                "matched": True,
                "iou": round(
                    time_iou(
                        int(g_norm["t0_ms"]),
                        int(g_norm["t1_ms"]),
                        int(p["t0_ms"]),
                        int(p["t1_ms"]),
                    ),
                    4,
                ),
                "flags": flags,
                "gold": {
                    "category": g_norm["chain_category"],
                    "first": g_norm["first_event"],
                    "last": g_norm["last_event"],
                    "t0_ms": g_norm["t0_ms"],
                    "t1_ms": g_norm["t1_ms"],
                },
                "pred": {
                    "category": p.get("chain_category"),
                    "first": p.get("first_event"),
                    "last": p.get("last_event"),
                    "t0_ms": p.get("t0_ms"),
                    "t1_ms": p.get("t1_ms"),
                },
            }
        )
    return rows


def summarize(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {
            "n": 0,
            "strict_complete": 0,
            "strict_rate": 0.0,
            "aux_time_cat_rate": 0.0,
            "aux_time_cat_last_rate": 0.0,
            "matched": 0,
        }
    strict = sum(1 for r in rows if r["flags"]["strict"])
    aux1 = sum(1 for r in rows if r["flags"]["aux_time_cat"])
    aux2 = sum(1 for r in rows if r["flags"]["aux_time_cat_last"])
    matched = sum(1 for r in rows if r["matched"])
    return {
        "n": n,
        "matched": matched,
        "strict_complete": strict,
        "strict_rate": round(100.0 * strict / n, 2),
        "aux_time_cat_complete": aux1,
        "aux_time_cat_rate": round(100.0 * aux1 / n, 2),
        "aux_time_cat_last_complete": aux2,
        "aux_time_cat_last_rate": round(100.0 * aux2 / n, 2),
    }
