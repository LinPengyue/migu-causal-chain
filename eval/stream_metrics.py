"""流式拆条计分：candidate track 跨 prefix 连续性关联（评测记账层）。

不改 strip 算法；仅把跨 prefix 的演化链归并为同一 track。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from metrics import check_pair, time_iou, time_overlap


def gold_t_ready(gold: Dict[str, Any]) -> int:
    """gold 末事件时间；此前不计漏检。"""
    times = []
    for e in gold.get("events") or []:
        if e.get("t_ms") is not None:
            times.append(int(e["t_ms"]))
    if times:
        return max(times)
    return int(gold.get("t1_ms") or gold.get("t0_ms") or 0)


def _event_id_set(pred: Dict[str, Any]) -> Set[str]:
    ids = pred.get("event_ids") or []
    return {str(x) for x in ids if x is not None and str(x)}


def _event_key_set(pred: Dict[str, Any]) -> Set[Tuple[int, str]]:
    keys = pred.get("event_keys")
    if keys:
        out = set()
        for k in keys:
            if isinstance(k, (list, tuple)) and len(k) >= 2:
                out.add((int(k[0]), str(k[1])))
            elif isinstance(k, dict) and k.get("t_ms") is not None:
                out.add((int(k["t_ms"]), str(k.get("type") or "")))
        return out
    # 回退：仅首末
    out = set()
    t0, t1 = int(pred.get("t0_ms") or 0), int(pred.get("t1_ms") or 0)
    f, l = pred.get("first_event") or "", pred.get("last_event") or ""
    if f:
        out.add((t0, str(f)))
    if l:
        out.add((t1, str(l)))
    return out


def _jaccard(a: Set, b: Set) -> float:
    if not a and not b:
        return 0.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _cat_compatible(a: str, b: str) -> bool:
    a, b = (a or ""), (b or "")
    if not a or not b:
        return True
    return a == b


def _template_compatible(a: str, b: str) -> bool:
    a, b = (a or ""), (b or "")
    if not a or not b:
        return True
    return a == b


def _first_compatible(a: str, b: str) -> bool:
    a, b = (a or ""), (b or "")
    if not a or not b:
        return True
    return a == b


def link_score(
    prev: Dict[str, Any],
    cur: Dict[str, Any],
    *,
    t0_slack_ms: int = 8_000,
    t1_slack_ms: int = 8_000,
) -> float:
    """前后两个 candidate 是否同一 track 的 continuity 分（越高越像同链演化）。"""
    p0, p1 = int(prev.get("t0_ms") or 0), int(prev.get("t1_ms") or 0)
    c0, c1 = int(cur.get("t0_ms") or 0), int(cur.get("t1_ms") or 0)

    ids_p, ids_c = _event_id_set(prev), _event_id_set(cur)
    keys_p, keys_c = _event_key_set(prev), _event_key_set(cur)

    # 旧链已结束后很久才出现、且事件几乎无继承 → 独立链（禁止跨时段误合并）
    gap = c0 - p1
    jac_ids = _jaccard(ids_p, ids_c) if (ids_p and ids_c) else 0.0
    jac_keys = _jaccard(keys_p, keys_c)
    jac = jac_ids if (ids_p and ids_c) else jac_keys
    subset = False
    if ids_p and ids_c:
        subset = ids_p <= ids_c or ids_c <= ids_p
    elif keys_p and keys_c:
        subset = keys_p <= keys_c or keys_c <= keys_p
    if gap > 60_000 and jac < 0.5 and not subset:
        return -1.0

    # 时间窗几乎无交 → 独立链
    if not time_overlap(p0, p1, c0, c1) and abs(c0 - p0) > t0_slack_ms and abs(c1 - p1) > t1_slack_ms:
        # 允许「后一个几乎完全覆盖前一个」的延长
        if not (c0 <= p0 + t0_slack_ms and c1 >= p1 - t1_slack_ms):
            return -1.0

    score = 0.0

    if ids_p and ids_c:
        score += 4.0 * jac_ids
        if jac_ids < 0.25 and not subset:
            return -1.0
        if subset:
            score += 1.5  # 集合包含 = 典型延长/收缩
    else:
        score += 3.0 * jac_keys
        if jac_keys < 0.2 and not subset:
            # 无重叠事件且非包含 → 倾向独立
            if abs(c0 - p0) > t0_slack_ms:
                return -1.0
        if subset:
            score += 1.0

    # 起点接近 / 向前小幅修正
    dt0 = abs(c0 - p0)
    if dt0 <= t0_slack_ms:
        score += 1.5 * (1.0 - dt0 / max(t0_slack_ms, 1))
    elif c0 < p0 and (p0 - c0) <= 30_000 and c1 >= p1 - t1_slack_ms:
        score += 0.8  # 回溯补事件
    else:
        score -= 1.0

    # t1 合理向后扩展或基本不动
    if c1 >= p1 - t1_slack_ms:
        score += 1.2
        if c1 > p1:
            score += 0.5
    else:
        score -= 0.8

    # 窗 IoU：演化中通常中高
    iou = time_iou(p0, p1, c0, c1)
    score += 1.5 * iou

    if _first_compatible(prev.get("first_event") or "", cur.get("first_event") or ""):
        score += 0.8
    else:
        # first 变了但事件集合高度包含，仍可能是边界修正
        if _jaccard(keys_p or ids_p, keys_c or ids_c) < 0.5:
            score -= 1.2

    if _cat_compatible(prev.get("chain_category") or "", cur.get("chain_category") or ""):
        score += 0.6
    else:
        score -= 0.4

    if _template_compatible(prev.get("template_id") or "", cur.get("template_id") or ""):
        score += 0.4

    # 后一个几乎是前一个的超集窗
    if c0 <= p0 + t0_slack_ms and c1 >= p1 - 500:
        score += 1.0

    return score


# 关联阈值：经验上同链演化通常 > 3
_LINK_THRESHOLD = 3.0


def build_candidate_tracks(
    timeline_preds: Sequence[Tuple[int, List[Dict[str, Any]]]],
    *,
    link_threshold: float = _LINK_THRESHOLD,
) -> List[Dict[str, Any]]:
    """跨 prefix 把演化中的 candidate 串成 track。

    每个 track:
      track_id, first_seen_t_ms, states[{prefix_t_ms, pred}], final_state
    """
    tracks: List[Dict[str, Any]] = []
    next_id = 0

    for t_i, preds in timeline_preds:
        t_i = int(t_i)
        assigned: Set[int] = set()
        # 贪心：按与现有 track 的最佳分数匹配
        cand_order = list(enumerate(preds))
        # 先处理更「完整」的（事件多 / 窗长）有利于吸收
        cand_order.sort(
            key=lambda ip: (
                -len(ip[1].get("event_ids") or ip[1].get("event_keys") or []),
                -(int(ip[1].get("t1_ms") or 0) - int(ip[1].get("t0_ms") or 0)),
            )
        )
        pending = []
        for _, p in cand_order:
            best_j, best_sc = None, link_threshold
            for j, tr in enumerate(tracks):
                if j in assigned:
                    continue
                sc = link_score(tr["final_state"], p)
                if sc > best_sc:
                    best_sc, best_j = sc, j
            if best_j is not None:
                tr = tracks[best_j]
                tr["states"].append({"prefix_t_ms": t_i, "pred": dict(p), "link_score": round(best_sc, 3)})
                tr["final_state"] = dict(p)
                tr["last_seen_t_ms"] = t_i
                assigned.add(best_j)
            else:
                pending.append(p)
        for p in pending:
            tracks.append(
                {
                    "track_id": next_id,
                    "first_seen_t_ms": t_i,
                    "last_seen_t_ms": t_i,
                    "states": [{"prefix_t_ms": t_i, "pred": dict(p), "link_score": None}],
                    "final_state": dict(p),
                }
            )
            next_id += 1
            assigned.add(len(tracks) - 1)

    return tracks


def track_as_emit(tr: Dict[str, Any]) -> Dict[str, Any]:
    """精确率分母用的一条 candidate = track 的最终态 + 记账元数据。"""
    final = dict(tr["final_state"])
    final["emit_t_ms"] = int(tr["first_seen_t_ms"])
    final["track_id"] = tr["track_id"]
    final["n_states"] = len(tr["states"])
    final["first_seen_t_ms"] = tr["first_seen_t_ms"]
    final["last_seen_t_ms"] = tr["last_seen_t_ms"]
    return final


def _pred_close(a: Dict[str, Any], b: Dict[str, Any], *, bucket_ms: int = 500) -> bool:
    """判断 snapshot pred 是否属于某 track 的某一态。"""
    if _event_id_set(a) and _event_id_set(b):
        if _jaccard(_event_id_set(a), _event_id_set(b)) >= 0.9:
            return True
    if abs(int(a.get("t0_ms") or 0) - int(b.get("t0_ms") or 0)) <= bucket_ms and abs(
        int(a.get("t1_ms") or 0) - int(b.get("t1_ms") or 0)
    ) <= bucket_ms:
        if (a.get("last_event") or "") == (b.get("last_event") or "") and (
            a.get("first_event") or ""
        ) == (b.get("first_event") or ""):
            return True
    # 同 track 演化：高重叠即可
    if link_score(a, b) >= link_threshold_for_identity():
        return True
    return False


def link_threshold_for_identity() -> float:
    return _LINK_THRESHOLD


def find_track_for_pred(
    tracks: Sequence[Dict[str, Any]],
    pred: Dict[str, Any],
    *,
    prefix_t_ms: Optional[int] = None,
) -> Optional[int]:
    best_j, best_sc = None, -1.0
    for j, tr in enumerate(tracks):
        # 优先看同 prefix 的 state
        for st in tr["states"]:
            if prefix_t_ms is not None and int(st["prefix_t_ms"]) != int(prefix_t_ms):
                continue
            if _pred_close(st["pred"], pred):
                return j
        sc = link_score(tr["final_state"], pred)
        if sc > best_sc:
            best_sc, best_j = sc, j
    if best_j is not None and best_sc >= _LINK_THRESHOLD:
        return best_j
    # 再扫全部 states
    for j, tr in enumerate(tracks):
        for st in tr["states"]:
            if _pred_close(st["pred"], pred):
                return j
    return None


def earliest_strict_in_track(
    gold: Dict[str, Any],
    track: Dict[str, Any],
    *,
    t_ready: int,
) -> Optional[Tuple[int, Dict[str, Any], Dict[str, bool]]]:
    """从 track 演化记录取首次严格匹配的 prefix。"""
    best = None
    for st in track["states"]:
        t_i = int(st["prefix_t_ms"])
        if t_i < t_ready:
            continue
        flags = match_flags(gold, st["pred"])
        if flags.get("strict"):
            if best is None or t_i < best[0]:
                best = (t_i, st["pred"], flags)
    return best


def match_flags(gold: Dict[str, Any], pred: Dict[str, Any]) -> Dict[str, bool]:
    g = {
        "chain_category": gold.get("chain_category") or "",
        "first_event": gold.get("first_event") or "",
        "last_event": gold.get("last_event") or "",
        "t0_ms": gold.get("t0_ms"),
        "t1_ms": gold.get("t1_ms"),
    }
    return check_pair(g, pred)


def _edge_weight(t_match: int, iou: float) -> int:
    """最大权匹配：先靠 BIG 拉满基数，其次更早首次严格命中、更高 IoU。"""
    # t_match 通常 < 1e8；iou∈[0,1]
    return 10**15 - int(t_match) + int(round(float(iou) * 1_000_000))


def _max_weight_one_to_one(
    n_gold: int,
    track_ids: Sequence[Any],
    edges: Sequence[Tuple[int, int, int, Dict[str, Any]]],
) -> Dict[int, Tuple[int, Dict[str, Any]]]:
    """gold_idx → (track_col, edge_payload).

    edges: (gold_idx, track_col, weight, payload)
    用赋值问题 + dummy 列允许未匹配；非边禁止占用 track。
    """
    if n_gold <= 0 or not track_ids:
        return {}
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    n_track = len(track_ids)
    # 列：真实 track + 每条 gold 一个「未匹配」dummy
    n_col = n_track + n_gold
    # minimize cost；非边用大惩罚，避免假匹配占坑
    BIG_COST = 10**18
    cost = np.full((n_gold, n_col), BIG_COST, dtype=np.float64)
    payload_map: Dict[Tuple[int, int], Dict[str, Any]] = {}
    best_w: Dict[Tuple[int, int], int] = {}

    for gi, tj, w, payload in edges:
        if gi < 0 or gi >= n_gold or tj < 0 or tj >= n_track:
            continue
        key = (gi, tj)
        if key in best_w and w <= best_w[key]:
            continue
        best_w[key] = w
        payload_map[key] = payload
        cost[gi, tj] = float(-w)

    for gi in range(n_gold):
        cost[gi, n_track + gi] = 0.0  # 未匹配

    row_ind, col_ind = linear_sum_assignment(cost)
    out: Dict[int, Tuple[int, Dict[str, Any]]] = {}
    for gi, cj in zip(row_ind.tolist(), col_ind.tolist()):
        if cj >= n_track:
            continue
        payload = payload_map.get((gi, cj))
        if payload is None:
            continue
        # 防御：若因数值问题落到非边，跳过
        if cost[gi, cj] >= BIG_COST / 2:
            continue
        out[gi] = (cj, payload)
    return out


def score_stream_match(
    golds: Sequence[Dict[str, Any]],
    timeline_preds: Sequence[Tuple[int, List[Dict[str, Any]]]],
    *,
    require_strict: bool = True,
    bucket_ms: int = 500,
) -> Dict[str, Any]:
    """A 主评测：track 连续性关联 + gold↔track 一对一最大权匹配。

    strict 判定不变；匹配层保证一场内一个 track 至多配一个 gold。
    """
    _ = bucket_ms  # 保留参数兼容
    tracks = build_candidate_tracks(timeline_preds)
    emits = [track_as_emit(tr) for tr in tracks]
    track_ids = [tr["track_id"] for tr in tracks]
    tid_to_col = {int(tid): j for j, tid in enumerate(track_ids)}

    # 收集可匹配边（strict 条件与旧口径相同）
    edges: List[Tuple[int, int, int, Dict[str, Any]]] = []
    for gi, g in enumerate(golds):
        t_ready = gold_t_ready(g)
        # 每个 (gold, track) 只保留最早严格命中
        best_per_track: Dict[int, Tuple[int, Dict[str, Any], Dict[str, bool]]] = {}
        for tr in tracks:
            hit = earliest_strict_in_track(g, tr, t_ready=t_ready)
            if hit is None:
                continue
            t_match, pred, flags = hit
            ok = flags["strict"] if require_strict else flags["aux_time_cat"]
            if not ok:
                continue
            tj = tid_to_col.get(int(tr["track_id"]))
            if tj is None:
                continue
            prev = best_per_track.get(tj)
            if prev is None or t_match < prev[0]:
                best_per_track[tj] = (t_match, pred, flags)

        # 回退：snapshot 命中且能挂到已有 track（不新建 orphan，避免破坏 track 分母）
        if not best_per_track:
            for t_i, preds in timeline_preds:
                if int(t_i) < t_ready:
                    continue
                for p in preds:
                    flags = match_flags(g, p)
                    ok = flags["strict"] if require_strict else flags["aux_time_cat"]
                    if not ok:
                        continue
                    tid = find_track_for_pred(tracks, p, prefix_t_ms=int(t_i))
                    if tid is None:
                        continue
                    tj = tid_to_col.get(int(tracks[tid]["track_id"]))
                    if tj is None:
                        continue
                    prev = best_per_track.get(tj)
                    if prev is None or int(t_i) < prev[0]:
                        best_per_track[tj] = (int(t_i), p, flags)

        for tj, (t_match, pred, flags) in best_per_track.items():
            iou = time_iou(
                int(g["t0_ms"]),
                int(g["t1_ms"]),
                int(pred.get("t0_ms") or 0),
                int(pred.get("t1_ms") or 0),
            )
            w = _edge_weight(int(t_match), iou)
            edges.append(
                (
                    gi,
                    tj,
                    w,
                    {
                        "t_match": int(t_match),
                        "pred": pred,
                        "flags": flags,
                        "track_id": int(track_ids[tj]),
                        "iou": iou,
                    },
                )
            )

    matched = _max_weight_one_to_one(len(golds), track_ids, edges)

    gold_rows: List[Dict[str, Any]] = []
    latencies: List[int] = []
    used_track: Set[int] = set()

    for gi, g in enumerate(golds):
        t_ready = gold_t_ready(g)
        if gi not in matched:
            gold_rows.append(
                {
                    "annotation_id": g.get("annotation_id"),
                    "t_ready": t_ready,
                    "matched": False,
                    "latency_ms": None,
                    "track_id": None,
                    "flags": {
                        "a_time": False,
                        "b_category": False,
                        "c_first": False,
                        "d_last": False,
                        "strict": False,
                        "aux_time_cat": False,
                        "aux_time_cat_last": False,
                    },
                    "pred": None,
                }
            )
            continue

        _tj, payload = matched[gi]
        pred = payload["pred"]
        flags = payload["flags"]
        track_id = payload["track_id"]
        t_match = int(payload["t_match"])
        latency = max(0, t_match - t_ready)
        latencies.append(latency)
        used_track.add(int(track_id))
        gold_rows.append(
            {
                "annotation_id": g.get("annotation_id"),
                "t_ready": t_ready,
                "matched": True,
                "latency_ms": latency,
                "track_id": track_id,
                "flags": flags,
                "pred": {
                    "category": pred.get("chain_category"),
                    "first": pred.get("first_event"),
                    "last": pred.get("last_event"),
                    "t0_ms": pred.get("t0_ms"),
                    "t1_ms": pred.get("t1_ms"),
                    "emit_t_ms": t_match,
                },
            }
        )

    n = len(gold_rows)
    n_strict = sum(1 for r in gold_rows if r["flags"].get("strict"))
    n_aux = sum(1 for r in gold_rows if r["flags"].get("aux_time_cat"))
    n_matched = sum(1 for r in gold_rows if r["matched"])
    n_emit = len(emits)
    n_prec_hit = len(used_track)
    # 一对一不变量
    assert n_matched == n_prec_hit, (
        f"one-to-one violated: matched_gold={n_matched} unique_tracks={n_prec_hit}"
    )

    def _pct(a: int, b: int) -> float:
        return round(100.0 * a / b, 2) if b else 0.0

    def _pctile(vals: List[int], q: float) -> Optional[float]:
        if not vals:
            return None
        xs = sorted(vals)
        if len(xs) == 1:
            return float(xs[0])
        idx = int(round(q * (len(xs) - 1)))
        return float(xs[idx])

    # 精简 track 摘要（避免报告过大）
    track_summaries = []
    for tr in tracks:
        track_summaries.append(
            {
                "track_id": tr["track_id"],
                "first_seen_t_ms": tr["first_seen_t_ms"],
                "last_seen_t_ms": tr["last_seen_t_ms"],
                "n_states": len(tr["states"]),
                "evolution": [
                    {
                        "prefix_t_ms": st["prefix_t_ms"],
                        "first": st["pred"].get("first_event"),
                        "last": st["pred"].get("last_event"),
                        "t0_ms": st["pred"].get("t0_ms"),
                        "t1_ms": st["pred"].get("t1_ms"),
                        "category": st["pred"].get("chain_category"),
                        "template_id": st["pred"].get("template_id"),
                    }
                    for st in tr["states"]
                ],
                "final_state": {
                    "first": tr["final_state"].get("first_event"),
                    "last": tr["final_state"].get("last_event"),
                    "t0_ms": tr["final_state"].get("t0_ms"),
                    "t1_ms": tr["final_state"].get("t1_ms"),
                    "category": tr["final_state"].get("chain_category"),
                    "template_id": tr["final_state"].get("template_id"),
                },
            }
        )

    return {
        "n_gold": n,
        "n_emit_deduped": n_emit,  # 兼容旧字段名 = track 数
        "n_tracks": n_emit,
        "recall_matched": n_matched,
        "n_matched_gold": n_matched,
        "n_unique_matched_tracks": n_prec_hit,
        "one_to_one_ok": n_matched == n_prec_hit,
        "recall_rate": _pct(n_matched, n),
        "strict_complete": n_strict,
        "strict_rate": _pct(n_strict, n),
        "aux_time_cat_complete": n_aux,
        "aux_time_cat_rate": _pct(n_aux, n),
        "precision_hits": n_prec_hit,
        "precision_rate": _pct(n_prec_hit, n_emit),
        "latency_ms_p50": _pctile(latencies, 0.50),
        "latency_ms_p90": _pctile(latencies, 0.90),
        "latency_ms_mean": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "gold_rows": gold_rows,
        "emits": emits,
        "tracks": track_summaries,
        "dedupe_mode": "candidate_track_continuity",
        "match_mode": "bipartite_max_weight_one_to_one",
    }


def score_oracle_upper(
    golds: Sequence[Dict[str, Any]],
    preds_per_gold: Sequence[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """B 上界：每条 gold 对应一次 oracle 输入上的 predict 结果。"""
    rows = []
    for g, preds in zip(golds, preds_per_gold):
        best_flags = None
        best_pred = None
        best_iou = -1.0
        for p in preds:
            flags = match_flags(g, p)
            iou = time_iou(
                int(g["t0_ms"]), int(g["t1_ms"]), int(p["t0_ms"]), int(p["t1_ms"])
            )
            if flags["strict"] or (best_flags is None and flags["a_time"]):
                if flags["strict"] and (best_flags is None or not best_flags.get("strict")):
                    best_flags, best_pred, best_iou = flags, p, iou
                elif flags["strict"] and iou > best_iou:
                    best_flags, best_pred, best_iou = flags, p, iou
                elif best_flags is None:
                    best_flags, best_pred, best_iou = flags, p, iou
            elif best_flags is None and iou > best_iou:
                best_flags, best_pred, best_iou = flags, p, iou
        if best_flags is None:
            best_flags = {
                "a_time": False,
                "b_category": False,
                "c_first": False,
                "d_last": False,
                "strict": False,
                "aux_time_cat": False,
                "aux_time_cat_last": False,
            }
        rows.append(
            {
                "annotation_id": g.get("annotation_id"),
                "matched": bool(best_pred is not None and best_flags.get("a_time")),
                "flags": best_flags,
                "pred": best_pred,
            }
        )
    n = len(rows)
    n_s = sum(1 for r in rows if r["flags"].get("strict"))
    n_a = sum(1 for r in rows if r["flags"].get("aux_time_cat"))

    def _pct(a: int, b: int) -> float:
        return round(100.0 * a / b, 2) if b else 0.0

    return {
        "n_gold": n,
        "strict_complete": n_s,
        "strict_rate": _pct(n_s, n),
        "aux_time_cat_complete": n_a,
        "aux_time_cat_rate": _pct(n_a, n),
        "rows": rows,
    }


def prefix_curve_for_gold(
    gold: Dict[str, Any],
    timeline_preds: Sequence[Tuple[int, List[Dict[str, Any]]]],
) -> List[Dict[str, Any]]:
    """C：ready 之后每个 prefix 是否已严格匹配。"""
    t_ready = gold_t_ready(gold)
    curve = []
    for t_i, preds in timeline_preds:
        if int(t_i) < t_ready:
            continue
        hit = any(match_flags(gold, p).get("strict") for p in preds)
        aux = any(match_flags(gold, p).get("aux_time_cat") for p in preds)
        curve.append(
            {
                "t_ms": int(t_i),
                "dt_from_ready_ms": int(t_i) - t_ready,
                "strict": hit,
                "aux_time_cat": aux,
                "n_preds": len(preds),
            }
        )
    return curve
