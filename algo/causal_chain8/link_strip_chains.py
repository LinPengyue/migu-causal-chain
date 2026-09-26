"""P5：集锦因果链 — 将 strip 因果链作为节点，建链间关系并编排。

关系（chain-level，边方向统一为叙事顺序 src → dst，即 src 先于 dst 出现）：
  - follow：时间连续（弱默认）
  - same_sequence：共享核心/终局事件（key/terminal），同一攻防；普通窗重叠不升级
  - correction_of：原结果链 → VAR/改判链（dst 修正 src）

编排：由关系导出 before-约束，再拓扑排序；不是最终仅靠 sort(t0)。
不臆造球队/比分等缺失字段。不改 causal_chain6 / P3 / P4。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# 链间关系阈值（启发式，本轮不调参追指标）
_SAME_SEQ_GAP_MS = 45_000
_CORRECTION_LOOKBACK_MS = 180_000
_CORRECTION_MARKERS = frozenset({"var", "disallowed_goal", "controversy"})
_RESULT_MARKERS = frozenset({"goal", "penalty"})
# 核心/终局事件：same_sequence 必须共享其中至少一项（id 优先，否则 t_ms+type）
_CORE_EVENT_TYPES = frozenset(
    {
        "goal",
        "disallowed_goal",
        "var",
        "penalty",
        "red_card",
        "shot",
        "keeper_save",
        "goal_line_clearance",
    }
)


def _time_iou(a0: int, a1: int, b0: int, b1: int) -> float:
    inter = max(0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    if union <= 0:
        return 0.0
    return inter / float(union)


def _jaccard(a: Set, b: Set) -> float:
    if not a and not b:
        return 0.0
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def _event_key_set(events: Sequence[Dict[str, Any]]) -> Set[Tuple[int, str]]:
    out: Set[Tuple[int, str]] = set()
    for e in events:
        if e.get("t_ms") is None or not e.get("type"):
            continue
        out.add((int(e["t_ms"]), str(e["type"])))
    return out


def _event_id_set(events: Sequence[Dict[str, Any]]) -> Set[str]:
    return {str(e["event_id"]) for e in events if e.get("event_id")}


def _core_event_ids(events: Sequence[Dict[str, Any]]) -> Set[str]:
    out: Set[str] = set()
    for e in events:
        if e.get("type") not in _CORE_EVENT_TYPES:
            continue
        if e.get("event_id") is None:
            continue
        out.add(str(e["event_id"]))
    return out


def _core_event_keys(events: Sequence[Dict[str, Any]]) -> Set[Tuple[int, str]]:
    out: Set[Tuple[int, str]] = set()
    for e in events:
        if e.get("type") not in _CORE_EVENT_TYPES:
            continue
        if e.get("t_ms") is None:
            continue
        out.add((int(e["t_ms"]), str(e["type"])))
    return out


@dataclass
class StripChainNode:
    strip_chain_id: str
    t0_ms: int
    t1_ms: int
    chain_category: str = ""
    template_id: str = ""
    first_event: str = ""
    last_event: str = ""
    events: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strip_chain_id": self.strip_chain_id,
            "t0_ms": self.t0_ms,
            "t1_ms": self.t1_ms,
            "chain_category": self.chain_category,
            "template_id": self.template_id,
            "first_event": self.first_event,
            "last_event": self.last_event,
            "events": list(self.events),
        }


def normalize_strip_chain(raw: Dict[str, Any], *, index: int = 0) -> StripChainNode:
    """兼容 strip_gold / strip clips / eval pred。"""
    sid = (
        raw.get("strip_chain_id")
        or raw.get("annotation_id")
        or raw.get("proposal_id")
        or raw.get("clip_id")
        or f"chain_{index:02d}"
    )
    events_in = list(raw.get("events") or [])
    events: List[Dict[str, Any]] = []
    for j, e in enumerate(events_in):
        if e.get("t_ms") is None or not e.get("type"):
            continue
        ev: Dict[str, Any] = {
            "order": int(e.get("order", j)),
            "type": str(e["type"]),
            "t_ms": int(e["t_ms"]),
        }
        if e.get("event_id") is not None:
            ev["event_id"] = str(e["event_id"])
        events.append(ev)

    if raw.get("t0_ms") is not None:
        t0 = int(raw["t0_ms"])
    elif events:
        t0 = min(int(e["t_ms"]) for e in events)
    else:
        t0 = 0
    if raw.get("t1_ms") is not None:
        t1 = int(raw["t1_ms"])
    elif events:
        t1 = max(int(e["t_ms"]) for e in events)
    else:
        t1 = t0

    first = str(raw.get("first_event") or (events[0]["type"] if events else ""))
    last = str(raw.get("last_event") or (events[-1]["type"] if events else ""))
    tid = str(
        raw.get("template_id")
        or raw.get("pred_chain_template_id")
        or raw.get("chain_template_id")
        or ""
    )
    cat = str(raw.get("chain_category") or "")
    if not cat and tid:
        try:
            from causal_chain6.schema.templates import CHAIN4_TEMPLATES

            cat = str((CHAIN4_TEMPLATES.get(tid) or {}).get("category") or "")
        except Exception:
            cat = ""
    return StripChainNode(
        strip_chain_id=str(sid),
        t0_ms=t0,
        t1_ms=t1,
        chain_category=cat,
        template_id=tid,
        first_event=first,
        last_event=last,
        events=events,
    )


def _is_correction_node(n: StripChainNode) -> bool:
    types = {e["type"] for e in n.events}
    if types & _CORRECTION_MARKERS:
        return True
    if n.chain_category == "correction" and (
        n.last_event in _CORRECTION_MARKERS or bool(types & _CORRECTION_MARKERS)
    ):
        return True
    if n.chain_category == "correction" and types <= _CORRECTION_MARKERS:
        return True
    # 纯 var / controversy 短链
    if n.chain_category == "correction" and len(n.events) <= 2:
        return True
    return False


def _is_result_target(n: StripChainNode) -> bool:
    types = {e["type"] for e in n.events}
    if types & _RESULT_MARKERS:
        return True
    if n.chain_category == "outcome":
        return True
    if n.last_event in _RESULT_MARKERS:
        return True
    return False


def _terminal_core_id(n: StripChainNode) -> Optional[str]:
    for e in reversed(n.events):
        if e.get("type") in _CORE_EVENT_TYPES and e.get("event_id") is not None:
            return str(e["event_id"])
    return None


def _shared_core(
    a: StripChainNode, b: StripChainNode
) -> Tuple[Set[str], Set[Tuple[int, str]]]:
    ids = _core_event_ids(a.events) & _core_event_ids(b.events)
    keys = _core_event_keys(a.events) & _core_event_keys(b.events)
    return ids, keys


def _same_sequence_score(a: StripChainNode, b: StripChainNode) -> float:
    """共享核心/终局事件才判 same_sequence；普通窗重叠/一般事件继承不够。"""
    if a.strip_chain_id == b.strip_chain_id:
        return -1.0
    x, y = (a, b) if a.t0_ms <= b.t0_ms else (b, a)
    gap = y.t0_ms - x.t1_ms
    iou = _time_iou(x.t0_ms, x.t1_ms, y.t0_ms, y.t1_ms)
    # 过远且无交 → 否
    if gap > _SAME_SEQ_GAP_MS and iou <= 0:
        return -1.0

    shared_ids, shared_keys = _shared_core(x, y)
    if not shared_ids and not shared_keys:
        return -1.0  # 无核心关联 → 由 follow 承接

    # 终局核心一致加分（同一 shot/goal/var）
    term_x, term_y = _terminal_core_id(x), _terminal_core_id(y)
    terminal_match = bool(term_x and term_y and term_x == term_y)

    score = 2.0 + 1.5 * len(shared_ids) + 1.0 * len(shared_keys)
    if terminal_match:
        score += 1.5
    if iou > 0:
        score += 0.5 * min(iou, 1.0)
    elif gap <= 0:
        score += 0.3
    elif gap <= _SAME_SEQ_GAP_MS:
        score += 0.2 * (1.0 - gap / _SAME_SEQ_GAP_MS)
    return score


def _correction_score(corr: StripChainNode, target: StripChainNode) -> float:
    """corr 是否修正 target；corr 应不早于 target。"""
    if corr.strip_chain_id == target.strip_chain_id:
        return -1.0
    if not _is_correction_node(corr):
        return -1.0
    if not _is_result_target(target):
        return -1.0
    # 修正链通常在结果之后或重叠
    if corr.t1_ms < target.t0_ms:
        return -1.0
    gap = corr.t0_ms - target.t1_ms
    if gap > _CORRECTION_LOOKBACK_MS:
        return -1.0
    if gap < -60_000:  # 修正远早于结果结束，不合理
        return -1.0
    score = 1.0
    if gap <= 0:
        score += 1.5
    elif gap <= 60_000:
        score += 1.2 * (1.0 - gap / 60_000)
    else:
        score += 0.4 * (1.0 - gap / _CORRECTION_LOOKBACK_MS)
    # 目标含进球 / 结果类更优先
    ttypes = {e["type"] for e in target.events}
    if "goal" in ttypes or target.last_event == "goal":
        score += 1.5
    if target.chain_category == "outcome":
        score += 0.5
    # 事件继承
    jac = _jaccard(_event_key_set(corr.events), _event_key_set(target.events))
    score += 0.8 * jac
    # 纯 var 短链贴近前一 goal 链
    ctypes = {e["type"] for e in corr.events}
    if ctypes <= _CORRECTION_MARKERS or ctypes & {"var", "disallowed_goal"}:
        score += 0.8
    return score


def build_chain_graph(
    nodes: List[StripChainNode],
) -> List[Dict[str, Any]]:
    """生成链间边；强关系优先，其余时间相邻退化为 follow。"""
    if not nodes:
        return []
    ordered = sorted(nodes, key=lambda n: (n.t0_ms, n.t1_ms, n.strip_chain_id))
    by_id = {n.strip_chain_id: n for n in ordered}
    edges: List[Dict[str, Any]] = []
    strong_pairs: Set[Tuple[str, str]] = set()

    # correction_of：每个修正链挂到最佳前序结果链
    for corr in ordered:
        if not _is_correction_node(corr):
            continue
        best: Optional[Tuple[float, StripChainNode]] = None
        for tgt in ordered:
            if tgt.t0_ms > corr.t1_ms:
                break
            sc = _correction_score(corr, tgt)
            if sc < 0:
                continue
            if best is None or sc > best[0]:
                best = (sc, tgt)
        if best is not None:
            sc, tgt = best
            # 叙事统一：src=原结果，dst=修正链（与 follow/same_sequence 同向）
            edges.append(
                {
                    "src": tgt.strip_chain_id,
                    "dst": corr.strip_chain_id,
                    "rel": "correction_of",
                    "score": round(sc, 4),
                    "reason": "result_then_correction",
                }
            )
            strong_pairs.add(tuple(sorted((corr.strip_chain_id, tgt.strip_chain_id))))

    # same_sequence：按「共享核心事件」建边；每个 core 只连时间上相邻的节点对
    # （避免普通重叠传递成超大连通块；A-B、B-C 仅当连续共享同一 core 时成链）
    core_groups: Dict[Any, List[StripChainNode]] = defaultdict(list)
    for n in ordered:
        cids = _core_event_ids(n.events)
        if cids:
            for cid in cids:
                core_groups[("id", cid)].append(n)
        else:
            for key in _core_event_keys(n.events):
                core_groups[("key", key)].append(n)

    seen_ss: Set[Tuple[str, str]] = set()
    for _core, group in core_groups.items():
        # 去重并按时间排
        uniq: Dict[str, StripChainNode] = {}
        for n in group:
            uniq[n.strip_chain_id] = n
        seq = sorted(uniq.values(), key=lambda n: (n.t0_ms, n.t1_ms, n.strip_chain_id))
        for i in range(len(seq) - 1):
            a, b = seq[i], seq[i + 1]
            pair = tuple(sorted((a.strip_chain_id, b.strip_chain_id)))
            if pair in strong_pairs or pair in seen_ss:
                continue
            sc = _same_sequence_score(a, b)
            if sc < 0:
                continue
            edges.append(
                {
                    "src": a.strip_chain_id,
                    "dst": b.strip_chain_id,
                    "rel": "same_sequence",
                    "score": round(sc, 4),
                    "reason": "shared_core_or_terminal_event",
                }
            )
            strong_pairs.add(pair)
            seen_ss.add(pair)

    # follow：时间相邻且无强关系（普通重叠降级到此）
    for i in range(len(ordered) - 1):
        a, b = ordered[i], ordered[i + 1]
        pair = tuple(sorted((a.strip_chain_id, b.strip_chain_id)))
        if pair in strong_pairs:
            continue
        edges.append(
            {
                "src": a.strip_chain_id,
                "dst": b.strip_chain_id,
                "rel": "follow",
                "score": 1.0,
                "reason": "temporal_adjacent_fallback",
            }
        )

    # 稳定：按 rel 优先级 + score
    rel_rank = {"correction_of": 0, "same_sequence": 1, "follow": 2}
    edges.sort(key=lambda e: (rel_rank.get(e["rel"], 9), -float(e["score"]), e["src"], e["dst"]))
    return edges


def _order_by_graph(
    nodes: List[StripChainNode],
    edges: List[Dict[str, Any]],
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """由关系导出 before 约束后拓扑排序；并列按 t0。

    边语义统一：src 在叙事上先于 dst（含 correction_of：原事件 → VAR/改判）。
    """
    ids = [n.strip_chain_id for n in sorted(nodes, key=lambda x: (x.t0_ms, x.t1_ms, x.strip_chain_id))]
    t0 = {n.strip_chain_id: n.t0_ms for n in nodes}
    before: Dict[str, Set[str]] = {i: set() for i in ids}  # u in before[v] => u before v
    preds: Dict[str, List[Tuple[str, str]]] = {i: [] for i in ids}  # v -> [(u, rel)]

    for e in edges:
        src, dst, rel = e["src"], e["dst"], e["rel"]
        if src not in before or dst not in before:
            continue
        if rel in ("follow", "same_sequence", "correction_of"):
            before[dst].add(src)
            preds[dst].append((src, rel))

    # Kahn
    indeg = {i: 0 for i in ids}
    succ: Dict[str, Set[str]] = {i: set() for i in ids}
    for v, us in before.items():
        for u in us:
            succ[u].add(v)
            indeg[v] += 1

    ready = sorted([i for i in ids if indeg[i] == 0], key=lambda x: (t0[x], x))
    ordering: List[str] = []
    while ready:
        u = ready.pop(0)
        ordering.append(u)
        for v in sorted(succ[u], key=lambda x: (t0[x], x)):
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)
                ready.sort(key=lambda x: (t0[x], x))

    # 环兜底：剩余按 t0
    if len(ordering) < len(ids):
        rest = [i for i in ids if i not in set(ordering)]
        rest.sort(key=lambda x: (t0[x], x))
        ordering.extend(rest)

    steps: List[Dict[str, Any]] = []
    for i, cid in enumerate(ordering):
        if i == 0:
            steps.append({"strip_chain_id": cid, "via_rel": "start", "from": None})
            continue
        via = None
        frm = None
        for u, rel in preds.get(cid, []):
            if u in ordering[:i]:
                via, frm = rel, u
                break
        if via is None:
            via, frm = "follow", ordering[i - 1]
        steps.append({"strip_chain_id": cid, "via_rel": via, "from": frm})
    return ordering, steps


def build_match_highlight_chain(
    strip_chains: Sequence[Dict[str, Any]],
    *,
    match_id: str = "",
    source: str = "strip_chains",
) -> Dict[str, Any]:
    """输入多条 strip chain → 全场 highlight_chain（nodes + edges + ordering）。"""
    nodes = [normalize_strip_chain(c, index=i) for i, c in enumerate(strip_chains)]
    # 去重 id
    seen: Set[str] = set()
    uniq: List[StripChainNode] = []
    for n in nodes:
        sid = n.strip_chain_id
        if sid in seen:
            sid = f"{sid}__{len(uniq)}"
            n = StripChainNode(
                strip_chain_id=sid,
                t0_ms=n.t0_ms,
                t1_ms=n.t1_ms,
                chain_category=n.chain_category,
                template_id=n.template_id,
                first_event=n.first_event,
                last_event=n.last_event,
                events=list(n.events),
            )
        seen.add(n.strip_chain_id)
        uniq.append(n)
    nodes = uniq
    edges = build_chain_graph(nodes)
    ordering, steps = _order_by_graph(nodes, edges)
    node_map = {n.strip_chain_id: n for n in nodes}
    rel_counts = {"follow": 0, "same_sequence": 0, "correction_of": 0}
    for e in edges:
        if e["rel"] in rel_counts:
            rel_counts[e["rel"]] += 1

    return {
        "match_id": match_id,
        "source": source,
        "nodes": [node_map[i].to_dict() for i in ordering if i in node_map],
        "edges": edges,
        "highlight_chain": {
            "ordering": ordering,
            "steps": steps,
        },
        "stats": {
            "n_strip_chains": len(nodes),
            "n_edges": len(edges),
            "rel_counts": rel_counts,
            "ordering_method": "graph_topo_from_relations",
            "n_correction_of": rel_counts["correction_of"],
        },
    }
