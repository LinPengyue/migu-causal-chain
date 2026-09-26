"""评测公共：数据加载、pred 规范化、统一报告 schema。不改算法。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets"
REPORTS = ROOT / "reports"


def load_index() -> Dict[str, Any]:
    return json.loads((DATA / "index.json").read_text(encoding="utf-8"))


def load_strip_gold(mdir: Path) -> List[Dict[str, Any]]:
    p = mdir / "strip_gold.json"
    if not p.exists():
        return []
    obj = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(obj, list):
        return obj
    return list(obj.get("chains") or [])


def load_highlight_gold(mdir: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """优先人工集锦 gold；返回 (chains, source_name)。空 chains 视为无有效 gold。"""
    for name in ("highlight_gold_no_t2.json", "highlight_gold.json", "highlight_gold_with_t2.json"):
        p = mdir / name
        if not p.exists():
            continue
        obj = json.loads(p.read_text(encoding="utf-8"))
        chains = obj.get("chains") if isinstance(obj, dict) else obj
        chains = list(chains or [])
        if chains:
            return chains, name
    return [], None


def label_source_counts(chains: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """统计 highlight gold 的 label_source（不改 gold）。"""
    counts = {"annotation": 0, "timeline_heuristic": 0}
    for c in chains:
        src = str(c.get("label_source") or "")
        if src == "annotation":
            counts["annotation"] += 1
        elif src == "timeline_heuristic":
            counts["timeline_heuristic"] += 1
        elif src:
            counts[src] = counts.get(src, 0) + 1
        else:
            counts["unknown"] = counts.get("unknown", 0) + 1
    return counts


def load_timeline_events(mdir: Path) -> List[Dict[str, Any]]:
    p = mdir / "timeline.json"
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    evs = raw.get("events") if isinstance(raw, dict) else raw
    out: List[Dict[str, Any]] = []
    for i, e in enumerate(evs or []):
        if e.get("t_ms") is None or not e.get("type"):
            continue
        out.append(
            {
                "order": int(e.get("order", i)),
                "type": e["type"],
                "t_ms": int(e["t_ms"]),
                "event_id": e.get("event_id") or f"t{i:04d}",
            }
        )
    out.sort(key=lambda x: (x["t_ms"], x["order"]))
    return out


def gold_events_stream(golds: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for g in golds:
        for e in g.get("events") or []:
            if e.get("t_ms") is None or not e.get("type"):
                continue
            key = (int(e["t_ms"]), str(e["type"]))
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "order": len(out),
                    "type": str(e["type"]),
                    "t_ms": int(e["t_ms"]),
                    "event_id": e.get("event_id") or f"g{len(out):04d}",
                }
            )
    out.sort(key=lambda x: (x["t_ms"], x["order"]))
    for i, e in enumerate(out):
        e["order"] = i
    return out


def timeline_slice_for_gold(
    gold: Dict[str, Any],
    timeline: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """仅 timeline 按 gold[t0,t1] 切片；空则返回 []（由调用方记 unscorable）。"""
    t0, t1 = int(gold["t0_ms"]), int(gold["t1_ms"])
    return [dict(e) for e in timeline if t0 <= int(e["t_ms"]) <= t1]


def gold_events_for_gold(gold: Dict[str, Any]) -> List[Dict[str, Any]]:
    """单模块评测：仅用 gold.events（仍走 strip，不走 classify）。"""
    out: List[Dict[str, Any]] = []
    for j, e in enumerate(gold.get("events") or []):
        if e.get("t_ms") is None or not e.get("type"):
            continue
        out.append(
            {
                "order": j,
                "type": str(e["type"]),
                "t_ms": int(e["t_ms"]),
                "event_id": e.get("event_id") or f"og{j:04d}",
            }
        )
    return out


def clip_events_for_gold(
    gold: Dict[str, Any],
    timeline: Sequence[Dict[str, Any]],
    *,
    event_source: str,
) -> List[Dict[str, Any]]:
    """显式 event_source：timeline | gold_events。无静默 fallback。"""
    if event_source == "timeline":
        return timeline_slice_for_gold(gold, timeline)
    if event_source == "gold_events":
        return gold_events_for_gold(gold)
    raise ValueError(f"unknown event_source={event_source!r}")


def highlight_clip_to_pred(chain: Any) -> Dict[str, Any]:
    """causal_chain8 HighlightChain / clip dict → matcher pred。"""
    if isinstance(chain, dict):
        evs = chain.get("events") or []
        first = ""
        last = ""
        if evs:
            e0, e1 = evs[0], evs[-1]
            first = str(e0.get("type") if isinstance(e0, dict) else getattr(e0, "type", "") or "")
            last = str(e1.get("type") if isinstance(e1, dict) else getattr(e1, "type", "") or "")
        cat = str(chain.get("chain_category") or "")
        return {
            "chain_category": cat,
            "first_event": first,
            "last_event": last,
            "t0_ms": int(chain.get("t0_ms") or 0),
            "t1_ms": int(chain.get("t1_ms") or 0),
            "template_id": str(chain.get("chain_template_id") or chain.get("template_id") or ""),
            "source": str(chain.get("clip_id") or ""),
        }
    events = list(getattr(chain, "events", None) or [])
    first = events[0].type if events else ""
    last = events[-1].type if events else ""
    return {
        "chain_category": str(getattr(chain, "chain_category", "") or ""),
        "first_event": first,
        "last_event": last,
        "t0_ms": int(chain.t0_ms),
        "t1_ms": int(chain.t1_ms),
        "template_id": str(getattr(chain, "chain_template_id", "") or ""),
        "source": str(getattr(chain, "clip_id", "") or ""),
    }


def build_highlight_clips(
    events: Sequence[Dict[str, Any]],
    *,
    match_id: str,
    profile: Dict[str, Any],
    drop_t2: bool = False,
    model=None,
    processor=None,
    device: str = "cpu",
    max_new_tokens: int = 512,
) -> Tuple[List[Any], Dict[str, Any]]:
    """复用 causal_chain8：select_moments → classify/refine → assemble_reel clips。"""
    from causal_chain8.assemble_reel import assemble_reel
    from causal_chain8.build_highlights import _moment_to_candidate
    from causal_chain8.refine import build_refined_chain, classify_candidate_chain4
    from causal_chain8.select_moments import select_moments

    evs = [dict(e) for e in events]
    moments, select_stats = select_moments(evs)
    if drop_t2:
        moments = [m for m in moments if m.tier != "T2"]
        select_stats = dict(select_stats)
        select_stats["drop_t2"] = True
        select_stats["n_selected_after_drop_t2"] = len(moments)

    built: List[Any] = []
    fast_n = 0
    for i, moment in enumerate(moments):
        cand = _moment_to_candidate(evs, moment, idx=i)
        tid, conf, margin, fast_path, _tr = classify_candidate_chain4(
            model,
            processor,
            evs,
            cand,
            profile=profile,
            device=device,
            max_new_tokens=max_new_tokens,
            match_id=match_id,
        )
        if fast_path:
            fast_n += 1
        chain = build_refined_chain(
            clip_id=f"clip{i:02d}",
            events=evs,
            candidate=cand,
            template_id=tid,
            confidence=conf,
            margin=margin,
            fast_path=fast_path,
            profile=profile,
            model=model,
            processor=processor,
            device=device,
            use_llm_narrative=False,
        )
        chain.t0_ms = moment.t0_ms
        chain.t1_ms = moment.t1_ms
        chain.validation = dict(chain.validation or {})
        chain.validation["selection"] = moment.to_dict()
        built.append(chain)

    final = assemble_reel(built)
    for j, c in enumerate(final):
        c.clip_id = f"clip{j:02d}"
    stats = {
        "moments_selected": len(moments),
        "clips_final": len(final),
        "fast_path": fast_n,
        "select": select_stats,
    }
    return final, stats


def should_drop_t2_for_gold(src_name: Optional[str], chains: Sequence[Dict[str, Any]]) -> bool:
    if src_name == "highlight_gold_no_t2.json":
        return True
    if chains and str(chains[0].get("highlight_mode") or "") == "no_t2":
        return True
    return False


def _slice_logic_stats(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    n_strict = sum(1 for r in rows if (r.get("flags") or {}).get("strict"))
    return {
        "total_gold": n,
        "strict_matched": n_strict,
        "logic_complete_rate": pct(n_strict, n) if n else None,
    }


def highlight_logic_by_label_source(
    golds: Sequence[Dict[str, Any]],
    rows: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """all / annotation-only / timeline_heuristic-only 逻辑完整率分层。"""
    assert len(golds) == len(rows)
    ann_rows: List[Dict[str, Any]] = []
    heur_rows: List[Dict[str, Any]] = []
    for g, r in zip(golds, rows):
        src = str(g.get("label_source") or "")
        if src == "annotation":
            ann_rows.append(r)
        elif src == "timeline_heuristic":
            heur_rows.append(r)
    return {
        "all": _slice_logic_stats(rows),
        "annotation_only": _slice_logic_stats(ann_rows),
        "timeline_heuristic_only": _slice_logic_stats(heur_rows),
    }


def node_to_pred(node: Dict[str, Any]) -> Dict[str, Any]:
    """highlight_chain node / strip clip → matcher pred schema。"""
    evs = node.get("events") or []
    first = str(node.get("first_event") or (evs[0].get("type") if evs else "") or "")
    last = str(node.get("last_event") or (evs[-1].get("type") if evs else "") or "")
    tid = str(
        node.get("template_id")
        or node.get("pred_chain_template_id")
        or node.get("chain_template_id")
        or ""
    )
    cat = str(node.get("chain_category") or "")
    if not cat and tid:
        try:
            from causal_chain6.schema.templates import CHAIN4_TEMPLATES

            cat = str((CHAIN4_TEMPLATES.get(tid) or {}).get("category") or "")
        except Exception:
            cat = ""
    event_ids = [str(e["event_id"]) for e in evs if e.get("event_id") is not None]
    event_keys = [
        [int(e["t_ms"]), str(e["type"])]
        for e in evs
        if e.get("t_ms") is not None and e.get("type")
    ]
    return {
        "chain_category": cat,
        "first_event": first,
        "last_event": last,
        "t0_ms": int(node.get("t0_ms") or 0),
        "t1_ms": int(node.get("t1_ms") or 0),
        "template_id": tid,
        "source": str(node.get("source") or node.get("strip_chain_id") or ""),
        "event_ids": event_ids,
        "event_keys": event_keys,
    }


def clip_to_strip_chain(clip: Dict[str, Any], *, index: int = 0) -> Dict[str, Any]:
    """AlgoStripAdapter / strip pipeline clip → link_strip_chains 输入。"""
    return {
        "strip_chain_id": clip.get("proposal_id")
        or clip.get("clip_id")
        or clip.get("strip_chain_id")
        or f"clip{index:02d}",
        "t0_ms": clip.get("t0_ms"),
        "t1_ms": clip.get("t1_ms"),
        "chain_category": clip.get("chain_category") or "",
        "template_id": clip.get("pred_chain_template_id")
        or clip.get("template_id")
        or "",
        "first_event": (clip.get("events") or [{}])[0].get("type")
        if clip.get("events")
        else clip.get("first_event") or "",
        "last_event": (clip.get("events") or [{}])[-1].get("type")
        if clip.get("events")
        else clip.get("last_event") or "",
        "events": list(clip.get("events") or []),
    }


def pct(a: int, b: int) -> Optional[float]:
    if b <= 0:
        return None
    return round(100.0 * a / b, 2)


def fmt_pct(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    return f"{float(x):.2f}%"


class _FallbackPbar:
    """无 tqdm 时的简易进度条。"""

    def __init__(self, desc: str, total: int) -> None:
        self.desc = desc
        self.total = max(int(total), 0)
        self.n = 0
        self._postfix = ""

    def set_postfix_str(self, s: str, refresh: bool = True) -> None:
        self._postfix = s
        if refresh:
            self._render()

    def set_postfix(self, ordered_dict=None, refresh: bool = True, **kwargs) -> None:
        parts = []
        if ordered_dict:
            for k, v in ordered_dict.items():
                parts.append(f"{k}={v}")
        for k, v in kwargs.items():
            parts.append(f"{k}={v}")
        self.set_postfix_str(" ".join(parts), refresh=refresh)

    def update(self, n: int = 1) -> None:
        self.n += n
        self._render()

    def _render(self) -> None:
        total = self.total or 1
        pct_done = 100.0 * self.n / total if self.total else 100.0
        bar_w = 10
        filled = int(bar_w * self.n / total) if self.total else bar_w
        bar = "█" * filled + "-" * (bar_w - filled)
        line = f"\r{self.desc}  {self.n}/{self.total} [{bar}] {pct_done:.0f}%"
        if self._postfix:
            line += f"  {self._postfix}"
        sys.stderr.write(line[:200])
        sys.stderr.flush()

    def close(self) -> None:
        sys.stderr.write("\n")
        sys.stderr.flush()

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()


def make_match_pbar(desc: str, total: int):
    """按比赛场次的进度条；优先 tqdm，否则 fallback。"""
    try:
        from tqdm import tqdm

        return tqdm(
            total=total,
            desc=desc,
            unit="match",
            dynamic_ncols=True,
            leave=True,
            file=sys.stderr,
        )
    except ImportError:
        return _FallbackPbar(desc, total)


def pctile(vals: List[int], q: float) -> Optional[float]:
    if not vals:
        return None
    xs = sorted(vals)
    return float(xs[int(round(q * (len(xs) - 1)))])


def empty_structural() -> Dict[str, Any]:
    return {
        "structural_pass_rate": None,
        "node_loss": None,
        "duplicate": None,
        "cycle": None,
        "ordering_stable": None,
        "correction_order_ok": None,
        "n_pass": 0,
        "n_fail": 0,
    }


def base_report(*, task: str, config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "task": task,
        "config": config,
        "total_gold": 0,
        "strict_matched": 0,
        "logic_complete_rate": None,
        "precision": None,
        "latency_p50": None,
        "latency_p90": None,
        "over_45s_rate": None,
        "structural": None,
        "n_matches": 0,
        "data_sources": {},
        "note": "",
    }


def has_cycle(ids: Sequence[str], edges: Sequence[Dict[str, Any]]) -> bool:
    from collections import defaultdict

    idset = set(ids)
    succ = defaultdict(set)
    for e in edges:
        s, d = e.get("src"), e.get("dst")
        if s in idset and d in idset:
            succ[s].add(d)
    color = {i: 0 for i in idset}

    def dfs(u: str) -> bool:
        color[u] = 1
        for v in succ[u]:
            if color[v] == 1:
                return True
            if color[v] == 0 and dfs(v):
                return True
        color[u] = 2
        return False

    return any(color[i] == 0 and dfs(i) for i in idset)
