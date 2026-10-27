#!/usr/bin/env python3
"""P1 失败归因（只读诊断）：不改 strip / 参数 / 评测指标 / Qwen。

对 rule-only + gold_events 输出：
  A/B 四象限、A primary failure、B✓A✗、B 内部、unmatched tracks、模板表、样例。
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "algo"))
sys.path.insert(0, str(ROOT / "eval"))

from causal_chain6.config import load_profile  # noqa: E402
from causal_chain6.llm.agent import classify_record_v4  # noqa: E402
from causal_chain6.io.eval_record import EvalRecord  # noqa: E402
from causal_chain6.schema.skeletons import CHAIN4_SKELETONS  # noqa: E402
from causal_chain6.schema.templates import CHAIN4_TEMPLATES  # noqa: E402
from causal_chain6.strip_pipeline import run_strip_highlights_events  # noqa: E402
from causal_chain2.segmentation_geom import ANCHOR_TYPES  # noqa: E402

from metrics import time_iou, time_overlap, check_pair  # noqa: E402
from run_stream_strip import (  # noqa: E402
    _load_strip_gold,
    _gold_events_stream,
    prefix_replay,
)
from stream_metrics import (  # noqa: E402
    build_candidate_tracks,
    earliest_strict_in_track,
    find_track_for_pred,
    gold_t_ready,
    match_flags,
    score_stream_match,
    _edge_weight,
    _max_weight_one_to_one,
)
from strip_adapter import AlgoStripAdapter  # noqa: E402

OUT = ROOT / "reports"
DATA = ROOT / "datasets"
TEMPLATE_IDS = list(CHAIN4_SKELETONS.keys())
CATS = ("outcome", "correction", "danger", "special")


def _pct(a: int, b: int) -> float:
    return round(100.0 * a / b, 2) if b else 0.0


def _overlap(g: Dict[str, Any], t0: int, t1: int) -> bool:
    return time_overlap(int(g["t0_ms"]), int(g["t1_ms"]), int(t0), int(t1))


def _iou_g(g: Dict[str, Any], t0: int, t1: int) -> float:
    return time_iou(int(g["t0_ms"]), int(g["t1_ms"]), int(t0), int(t1))


def _gold_events_norm(g: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for j, e in enumerate(g.get("events") or []):
        if e.get("t_ms") is None or not e.get("type"):
            continue
        out.append(
            {
                "order": int(e.get("order", j)),
                "type": str(e["type"]),
                "t_ms": int(e["t_ms"]),
                "event_id": e.get("event_id") or f"ge{j:04d}",
            }
        )
    return out


def classify_gold_template(g: Dict[str, Any], profile: Dict[str, Any]) -> str:
    events = _gold_events_norm(g)
    if not events:
        return ""
    rec = EvalRecord(
        annotation_id=str(g.get("annotation_id") or ""),
        match_id=str(g.get("match_id") or "eval"),
        gold_template_id="",
        gold_category=str(g.get("chain_category") or ""),
        gold_label_zh="",
        gold_category_zh="",
        events_raw=list(events),
        events_normalized=list(events),
        events_extracted=list(events),
    )
    result = classify_record_v4(
        rec, profile=profile, model=None, processor=None, device="cpu", max_new_tokens=512
    )
    return str(result.chain_template_id or "")


def run_strip_full(adapter: AlgoStripAdapter, events: List[Dict[str, Any]], match_id: str) -> Dict[str, Any]:
    return run_strip_highlights_events(
        events=events,
        match_id=match_id,
        profile=adapter.profile,
        model=None,
        processor=None,
        device="cpu",
        max_new_tokens=512,
        pre_ms=adapter.pre_ms,
        post_ms=adapter.post_ms,
        window_ms=adapter.window_ms,
        step_ms=adapter.step_ms,
        min_margin=adapter.min_margin,
        min_prob_top1=adapter.min_prob_top1,
        iou_dedupe_thresh=adapter.iou_dedupe,
        iou_recall_thresh=adapter.iou_recall,
        max_events=adapter.max_events,
        use_sliding_recall=adapter.use_sliding_recall,
        template_whitelist=None,
        input_file=f"diag:{match_id}",
        sliding_merge_mode=getattr(adapter, "sliding_merge_mode", "legacy"),
        sliding_post_nms=getattr(adapter, "sliding_post_nms", "off"),
    )


def geom_related(g: Dict[str, Any], geom_list: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [x for x in geom_list if _overlap(g, int(x["t0_ms"]), int(x["t1_ms"]))]


def scored_related(g: Dict[str, Any], scored: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [x for x in scored if _overlap(g, int(x["t0_ms"]), int(x["t1_ms"]))]


def collect_strict_edges(
    golds: Sequence[Dict[str, Any]],
    tracks: Sequence[Dict[str, Any]],
    timeline_preds: Sequence[Tuple[int, List[Dict[str, Any]]]],
) -> List[Tuple[int, int, int, Dict[str, Any]]]:
    """(gold_idx, track_col, weight, payload) — 与 score_stream_match 同口径。"""
    track_ids = [tr["track_id"] for tr in tracks]
    tid_to_col = {int(tid): j for j, tid in enumerate(track_ids)}
    edges: List[Tuple[int, int, int, Dict[str, Any]]] = []
    for gi, g in enumerate(golds):
        t_ready = gold_t_ready(g)
        best_per_track: Dict[int, Tuple[int, Dict[str, Any], Dict[str, bool]]] = {}
        for tr in tracks:
            hit = earliest_strict_in_track(g, tr, t_ready=t_ready)
            if hit is None:
                continue
            t_match, pred, flags = hit
            if not flags.get("strict"):
                continue
            tj = tid_to_col.get(int(tr["track_id"]))
            if tj is None:
                continue
            prev = best_per_track.get(tj)
            if prev is None or t_match < prev[0]:
                best_per_track[tj] = (t_match, pred, flags)
        if not best_per_track:
            for t_i, preds in timeline_preds:
                if int(t_i) < t_ready:
                    continue
                for p in preds:
                    flags = match_flags(g, p)
                    if not flags.get("strict"):
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
            iou = _iou_g(g, int(pred.get("t0_ms") or 0), int(pred.get("t1_ms") or 0))
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
    return edges


def best_overlapping_track(
    g: Dict[str, Any], tracks: Sequence[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    best = None
    best_iou = -1.0
    for tr in tracks:
        fs = tr["final_state"]
        iou = _iou_g(g, int(fs.get("t0_ms") or 0), int(fs.get("t1_ms") or 0))
        if iou <= 0 and not _overlap(g, int(fs.get("t0_ms") or 0), int(fs.get("t1_ms") or 0)):
            continue
        if iou > best_iou:
            best_iou = iou
            best = tr
    return best


def analyze_b_internal(g: Dict[str, Any], strip_out: Dict[str, Any]) -> Dict[str, Any]:
    """B✗ / strip 内部下钻（互斥优先序）。"""
    ag = geom_related(g, strip_out.get("anchor_geom") or [])
    sg = geom_related(g, strip_out.get("sliding_geom") or [])
    ascore = scored_related(g, strip_out.get("anchor_scored") or [])
    sscore = scored_related(g, strip_out.get("sliding_scored") or [])
    all_scored = ascore + sscore
    clips = [
        c
        for c in (strip_out.get("clips") or [])
        if _overlap(g, int(c.get("t0_ms") or 0), int(c.get("t1_ms") or 0))
    ]

    gold_has_anchor_type = any(
        (e.get("type") in ANCHOR_TYPES) for e in (g.get("events") or [])
    )

    detail = {
        "n_anchor_geom": len(ag),
        "n_sliding_geom": len(sg),
        "n_scored_related": len(all_scored),
        "n_clips_related": len(clips),
        "gold_has_anchor_type": gold_has_anchor_type,
    }

    if not ag and not sg:
        if not gold_has_anchor_type and not sg:
            reason = "no_geom_candidate"
            sub = "anchor_uncovered_and_sliding_miss" if True else ""
        else:
            reason = "no_geom_candidate"
            sub = "anchor_uncovered" if not ag else "sliding_miss"
        # refine
        if not ag and not gold_has_anchor_type:
            sub = "anchor_not_applicable"
        elif not ag and gold_has_anchor_type:
            sub = "anchor_miss_despite_type"
        if not sg:
            sub = (sub + "+sliding_miss") if sub else "sliding_miss"
        return {"primary": reason, "sub": sub, **detail}

    if all_scored and not any(x.get("passes_margin") for x in all_scored):
        return {"primary": "geom_scored_but_filtered", "sub": "min_margin_or_prob", **detail}

    passed = [x for x in all_scored if x.get("passes_margin")]
    in_sel = [
        x
        for x in passed
        if x.get("in_anchor_selected") or x.get("in_sliding_selected") or x.get("in_final_clips")
    ]
    if passed and not any(x.get("in_final_clips") for x in all_scored) and not clips:
        # disappeared in dedupe / supplement
        if any(x.get("in_anchor_selected") or x.get("in_sliding_selected") for x in all_scored):
            return {"primary": "lost_after_combined_dedupe", "sub": "final_dedupe", **detail}
        if passed and not in_sel:
            return {"primary": "lost_after_dedupe_or_supplement", "sub": "anchor_dedupe_or_sliding_supp", **detail}
        return {"primary": "lost_after_dedupe_or_supplement", "sub": "unknown_stage", **detail}

    # has outputs — classify mismatch type on best clip
    best_p = None
    best_iou = -1.0
    for c in strip_out.get("clips") or []:
        pred = {
            "chain_category": (CHAIN4_TEMPLATES.get(c.get("pred_chain_template_id") or "") or {}).get(
                "category", ""
            )
            or c.get("chain_category")
            or "",
            "first_event": (c.get("events") or [{}])[0].get("type") if c.get("events") else "",
            "last_event": (c.get("events") or [{}])[-1].get("type") if c.get("events") else "",
            "t0_ms": c.get("t0_ms"),
            "t1_ms": c.get("t1_ms"),
        }
        if c.get("events"):
            pred["first_event"] = str(c["events"][0].get("type") or "")
            pred["last_event"] = str(c["events"][-1].get("type") or "")
        tid = c.get("pred_chain_template_id") or ""
        if not pred["chain_category"] and tid in CHAIN4_TEMPLATES:
            pred["chain_category"] = CHAIN4_TEMPLATES[tid]["category"]
        iou = _iou_g(g, int(pred["t0_ms"] or 0), int(pred["t1_ms"] or 0))
        if iou > best_iou:
            best_iou = iou
            best_p = pred
    if best_p is None:
        return {"primary": "strip_empty_after_pipeline", "sub": "no_clip", **detail}

    flags = match_flags(g, best_p)
    if flags.get("strict"):
        return {"primary": "unexpected_b_ok_on_best", "sub": "", "flags": flags, **detail}
    if not flags.get("b_category"):
        return {"primary": "strip_out_category_wrong", "sub": "", "flags": flags, "pred": best_p, **detail}
    if not flags.get("c_first") and not flags.get("d_last"):
        return {"primary": "strip_out_both_boundary_wrong", "sub": "", "flags": flags, "pred": best_p, **detail}
    if not flags.get("c_first"):
        return {"primary": "strip_out_first_wrong", "sub": "", "flags": flags, "pred": best_p, **detail}
    if not flags.get("d_last"):
        return {"primary": "strip_out_last_wrong", "sub": "", "flags": flags, "pred": best_p, **detail}
    if not flags.get("a_time"):
        return {"primary": "strip_out_time_miss", "sub": "", "flags": flags, "pred": best_p, **detail}
    return {"primary": "strip_out_other", "sub": "", "flags": flags, "pred": best_p, **detail}


def a_primary_failure(
    g: Dict[str, Any],
    *,
    gi: int,
    matched: bool,
    assigned_track: Optional[int],
    edges_for_gold: List[Tuple[int, int, int, Dict[str, Any]]],
    matched_map: Dict[int, Tuple[int, Dict[str, Any]]],
    tracks: Sequence[Dict[str, Any]],
    full_strip: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    """互斥第一失败点。"""
    if matched:
        return "matched", {}

    # F7: had strict edge(s) but not assigned
    if edges_for_gold:
        # check if any of those tracks were given to another gold
        conflict_tracks = []
        for _gi, tj, _w, payload in edges_for_gold:
            taken_by = None
            for og, (otj, opayload) in matched_map.items():
                if otj == tj and og != gi:
                    taken_by = og
                    break
            if taken_by is not None:
                conflict_tracks.append(
                    {
                        "track_id": payload["track_id"],
                        "taken_by_gold_idx": taken_by,
                        "iou": payload.get("iou"),
                        "t_match": payload.get("t_match"),
                    }
                )
        if conflict_tracks:
            return "F7_one_to_one_conflict", {"conflicts": conflict_tracks}

    ag = geom_related(g, full_strip.get("anchor_geom") or [])
    sg = geom_related(g, full_strip.get("sliding_geom") or [])
    tr = best_overlapping_track(g, tracks)

    if not ag and not sg and tr is None:
        dep = []
        if not ag:
            dep.append("no_anchor")
        if not sg:
            dep.append("no_sliding")
        return "F1_no_candidate_generated", {
            "depends": dep,
            "gold_has_anchor_type": any(
                e.get("type") in ANCHOR_TYPES for e in (g.get("events") or [])
            ),
        }

    if tr is None:
        # geom existed on full stream but no track from prefix replay
        ascore = scored_related(g, full_strip.get("anchor_scored") or [])
        sscore = scored_related(g, full_strip.get("sliding_scored") or [])
        stage = "unknown"
        all_s = ascore + sscore
        if not all_s and (ag or sg):
            stage = "geom_only_no_score_unexpected"
        elif all_s and not any(x.get("passes_margin") for x in all_s):
            stage = "filtered_margin"
        elif all_s and not any(x.get("in_final_clips") for x in all_s):
            stage = "lost_dedupe_or_supplement"
        elif any(x.get("in_final_clips") for x in all_s):
            stage = "final_clip_exists_but_no_stream_track"
        return "F2_candidate_generated_but_no_track", {
            "disappear_stage": stage,
            "n_anchor_geom": len(ag),
            "n_sliding_geom": len(sg),
        }

    fs = tr["final_state"]
    pred = {
        "chain_category": fs.get("chain_category") or "",
        "first_event": fs.get("first_event") or "",
        "last_event": fs.get("last_event") or "",
        "t0_ms": fs.get("t0_ms"),
        "t1_ms": fs.get("t1_ms"),
    }
    flags = match_flags(g, pred)
    meta = {
        "track_id": tr["track_id"],
        "iou": _iou_g(g, int(pred["t0_ms"] or 0), int(pred["t1_ms"] or 0)),
        "pred": {
            "cat": pred["chain_category"],
            "first": pred["first_event"],
            "last": pred["last_event"],
            "t0_ms": pred["t0_ms"],
            "t1_ms": pred["t1_ms"],
        },
        "gold": {
            "cat": g.get("chain_category"),
            "first": g.get("first_event"),
            "last": g.get("last_event"),
            "t0_ms": g.get("t0_ms"),
            "t1_ms": g.get("t1_ms"),
        },
        "flags": flags,
        "n_states": len(tr["states"]),
    }
    # boundary subtype hints
    if flags.get("b_category") and not flags.get("c_first"):
        gt0 = int(g["t0_ms"])
        pt0 = int(pred["t0_ms"] or 0)
        if pt0 > gt0 + 1500:
            meta["first_issue"] = "truncated_front"
        elif pt0 < gt0 - 1500:
            meta["first_issue"] = "start_too_early"
        else:
            meta["first_issue"] = "adjacent_or_type_mismatch"
    if flags.get("b_category") and not flags.get("d_last"):
        gt1 = int(g["t1_ms"])
        pt1 = int(pred["t1_ms"] or 0)
        if pt1 < gt1 - 1500:
            meta["last_issue"] = "closed_too_early"
        elif pt1 > gt1 + 1500:
            meta["last_issue"] = "extended_into_next"
        else:
            meta["last_issue"] = "terminal_type_mismatch"

    if not flags.get("b_category"):
        return "F3_track_exists_category_wrong", meta
    if not flags.get("c_first") and not flags.get("d_last"):
        return "F6_track_exists_both_boundary_wrong", meta
    if not flags.get("c_first"):
        return "F4_track_exists_first_wrong", meta
    if not flags.get("d_last"):
        return "F5_track_exists_last_wrong", meta
    if not flags.get("a_time"):
        return "F3_track_exists_category_wrong", {**meta, "note": "time_miss_with_cat"}  # rare
    # track looks strict on final but A unmatched without F7 — treat as conflict/other
    return "F7_one_to_one_conflict", {**meta, "note": "final_looks_strict_but_unmatched"}


def reason_b_ok_a_fail(
    g: Dict[str, Any],
    *,
    a_reason: str,
    a_meta: Dict[str, Any],
    tracks: Sequence[Dict[str, Any]],
    b_pred: Optional[Dict[str, Any]],
    golds: Sequence[Dict[str, Any]],
    matched_track_ids: Set[int],
) -> str:
    if a_reason == "F7_one_to_one_conflict":
        return "one_to_one_conflict"
    if a_reason == "F1_no_candidate_generated":
        return "no_candidate_in_prefix"
    if a_reason == "F2_candidate_generated_but_no_track":
        return "no_candidate_in_prefix"

    tr = best_overlapping_track(g, tracks)
    if tr is None:
        return "no_candidate_in_prefix"

    # multi-gold merge: track overlaps multiple golds
    n_overlap_golds = 0
    for og in golds:
        fs = tr["final_state"]
        if _overlap(og, int(fs.get("t0_ms") or 0), int(fs.get("t1_ms") or 0)):
            n_overlap_golds += 1
    if n_overlap_golds >= 2:
        # check if any state was ever strict for this gold
        t_ready = gold_t_ready(g)
        ever_strict = earliest_strict_in_track(g, tr, t_ready=t_ready) is not None
        if ever_strict:
            return "track_merges_multi_gold"
        # boundary expanded?
        ious = []
        for st in tr["states"]:
            p = st["pred"]
            ious.append(_iou_g(g, int(p.get("t0_ms") or 0), int(p.get("t1_ms") or 0)))
        if ious and max(ious) > ious[-1] + 0.05:
            return "boundary_expands_merge"
        return "track_merges_multi_gold"

    # category instability across states
    cats = [st["pred"].get("chain_category") for st in tr["states"]]
    cats = [c for c in cats if c]
    if len(set(cats)) >= 2:
        return "category_unstable"

    if a_reason == "F4_track_exists_first_wrong":
        return "first_not_backfilled"
    if a_reason == "F5_track_exists_last_wrong":
        return "last_not_closed"
    if a_reason == "F6_track_exists_both_boundary_wrong":
        # which side worse
        issue_f = a_meta.get("first_issue")
        issue_l = a_meta.get("last_issue")
        if issue_l == "extended_into_next":
            return "boundary_expands_merge"
        if issue_f == "truncated_front":
            return "first_not_backfilled"
        return "last_not_closed"
    if a_reason == "F3_track_exists_category_wrong":
        return "category_unstable"

    # late candidate: first state after t_ready by a lot vs B
    if b_pred and tr["states"]:
        t_ready = gold_t_ready(g)
        first_t = int(tr["states"][0]["prefix_t_ms"])
        if first_t > t_ready + 30_000:
            return "candidate_too_late"

    return "no_candidate_in_prefix"


def classify_unmatched_track(
    tr: Dict[str, Any],
    golds: Sequence[Dict[str, Any]],
    matched_tracks: Sequence[Dict[str, Any]],
) -> Tuple[str, Dict[str, Any]]:
    fs = tr["final_state"]
    t0, t1 = int(fs.get("t0_ms") or 0), int(fs.get("t1_ms") or 0)
    # P1 duplicate_like
    for mt in matched_tracks:
        mfs = mt["final_state"]
        iou = time_iou(t0, t1, int(mfs.get("t0_ms") or 0), int(mfs.get("t1_ms") or 0))
        same_cat = (fs.get("chain_category") or "") == (mfs.get("chain_category") or "")
        if iou >= 0.7 and same_cat:
            return "P1_duplicate_like", {"iou_vs_matched": iou, "matched_track_id": mt["track_id"]}

    overlapping = []
    for g in golds:
        if _overlap(g, t0, t1) or _iou_g(g, t0, t1) > 0:
            overlapping.append(g)
    if len(overlapping) >= 2:
        return "P2_merged_multi_gold", {
            "n_golds": len(overlapping),
            "ann_ids": [g.get("annotation_id") for g in overlapping[:5]],
        }
    if len(overlapping) == 1:
        g = overlapping[0]
        pred = {
            "chain_category": fs.get("chain_category") or "",
            "first_event": fs.get("first_event") or "",
            "last_event": fs.get("last_event") or "",
            "t0_ms": t0,
            "t1_ms": t1,
        }
        flags = match_flags(g, pred)
        if not flags.get("b_category"):
            return "P4_wrong_category", {"ann": g.get("annotation_id"), "flags": flags}
        if flags.get("b_category") and (not flags.get("c_first") or not flags.get("d_last")):
            return "P3_boundary_shift", {"ann": g.get("annotation_id"), "flags": flags}
        return "P3_boundary_shift", {"ann": g.get("annotation_id"), "flags": flags, "note": "time_or_other"}
    return "P5_genuine_spurious", {"t0_ms": t0, "t1_ms": t1, "cat": fs.get("chain_category")}


def clip_to_pred(c: Dict[str, Any]) -> Dict[str, Any]:
    evs = c.get("events") or []
    first = str(evs[0].get("type") or "") if evs else ""
    last = str(evs[-1].get("type") or "") if evs else ""
    tid = c.get("pred_chain_template_id") or ""
    cat = c.get("chain_category") or ""
    if not cat and tid in CHAIN4_TEMPLATES:
        cat = CHAIN4_TEMPLATES[tid]["category"]
    return {
        "chain_category": cat,
        "first_event": first,
        "last_event": last,
        "t0_ms": int(c.get("t0_ms") or 0),
        "t1_ms": int(c.get("t1_ms") or 0),
        "template_id": tid,
        "source": c.get("source") or "",
    }


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="P1 failure attribution diagnostic")
    ap.add_argument("--profile", default="production")
    ap.add_argument("--out-json", default="")
    ap.add_argument("--out-md", default="")
    args = ap.parse_args()

    adapter = AlgoStripAdapter(
        profile_name=args.profile, use_llm=False, use_sliding_recall=True, device="cpu"
    )
    profile = dict(adapter.profile)
    profile.setdefault("llm", {})
    profile["llm"] = dict(profile.get("llm") or {})
    profile["llm"]["enabled"] = False
    print(
        f"profile={args.profile} sliding_merge_mode={adapter.sliding_merge_mode}",
        flush=True,
    )

    index = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    matches = index["matches"]

    # aggregators
    quad = Counter()
    quad_by_cat: Dict[str, Counter] = defaultdict(Counter)
    quad_by_tpl: Dict[str, Counter] = defaultdict(Counter)
    a_fail_reasons = Counter()
    a_fail_by_cat: Dict[str, Counter] = defaultdict(Counter)
    a_fail_by_tpl: Dict[str, Counter] = defaultdict(Counter)
    ba_reasons = Counter()
    b_fail_reasons = Counter()
    fp_reasons = Counter()
    tpl_stats: Dict[str, Dict[str, int]] = {
        tid: {"gold": 0, "a_strict": 0, "b_strict": 0} for tid in TEMPLATE_IDS
    }
    tpl_stats[""] = {"gold": 0, "a_strict": 0, "b_strict": 0}
    cat_stats: Dict[str, Dict[str, int]] = {
        c: {"gold": 0, "a_strict": 0, "b_strict": 0} for c in CATS
    }

    samples_a: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    samples_ba: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    samples_b: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    samples_fp: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    samples_axbx: List[Dict[str, Any]] = []

    gold_records: List[Dict[str, Any]] = []
    n_tracks_total = 0
    n_matched_tracks = 0
    n_unmatched_tracks = 0

    for mi, meta in enumerate(matches):
        mdir = ROOT / meta["dir"]
        safe = meta["safe_id"]
        golds = _load_strip_gold(mdir)
        if not golds:
            continue
        events = _gold_events_stream(golds)
        print(
            f"[{mi+1}/{len(matches)}] {safe[:44]} gold={len(golds)} events={len(events)}",
            flush=True,
        )

        # templates for golds
        templates = [classify_gold_template(g, profile) for g in golds]

        # A: prefix replay
        timeline_preds = prefix_replay(
            events, adapter, match_id=safe, stride=1, min_prefix=2
        )
        tracks = build_candidate_tracks(timeline_preds)
        edges = collect_strict_edges(golds, tracks, timeline_preds)
        track_ids = [tr["track_id"] for tr in tracks]
        matched_map = _max_weight_one_to_one(len(golds), track_ids, edges)
        sm = score_stream_match(golds, timeline_preds, require_strict=True)
        # trust official sm for A matched flags
        a_matched = [bool(r.get("matched")) for r in sm["gold_rows"]]
        a_track_ids = [r.get("track_id") for r in sm["gold_rows"]]

        # full-stream strip for geom diagnostics
        full_strip = run_strip_full(adapter, events, match_id=f"{safe}:full")

        # B per gold
        b_ok_list: List[bool] = []
        b_preds: List[Optional[Dict[str, Any]]] = []
        b_internals: List[Dict[str, Any]] = []
        for g in golds:
            t0, t1 = int(g["t0_ms"]), int(g["t1_ms"])
            sl = [e for e in events if t0 <= int(e["t_ms"]) <= t1]
            if not sl:
                # gold_events source: fallback to gold events themselves (same as eval B for gold_events)
                sl = _gold_events_norm(g)
            bout = run_strip_full(adapter, sl, match_id=f"{safe}:B:{g.get('annotation_id')}")
            preds = [clip_to_pred(c) for c in (bout.get("clips") or [])]
            best_flags = None
            best_pred = None
            best_iou = -1.0
            for p in preds:
                flags = match_flags(g, p)
                iou = _iou_g(g, int(p["t0_ms"]), int(p["t1_ms"]))
                if flags.get("strict") and (best_flags is None or not best_flags.get("strict") or iou > best_iou):
                    best_flags, best_pred, best_iou = flags, p, iou
                elif best_flags is None and iou > best_iou:
                    best_flags, best_pred, best_iou = flags, p, iou
            ok = bool(best_flags and best_flags.get("strict"))
            b_ok_list.append(ok)
            b_preds.append(best_pred if ok else best_pred)
            if ok:
                b_internals.append({"primary": "b_ok", "pred": best_pred})
            else:
                b_internals.append(analyze_b_internal(g, bout))

        edges_by_gold: Dict[int, List] = defaultdict(list)
        for e in edges:
            edges_by_gold[e[0]].append(e)

        matched_track_id_set: Set[int] = set()
        for tid in a_track_ids:
            if tid is not None:
                matched_track_id_set.add(int(tid))

        matched_tracks = [tr for tr in tracks if int(tr["track_id"]) in matched_track_id_set]
        unmatched = [tr for tr in tracks if int(tr["track_id"]) not in matched_track_id_set]
        n_tracks_total += len(tracks)
        n_matched_tracks += len(matched_tracks)
        n_unmatched_tracks += len(unmatched)

        for tr in unmatched:
            fp_r, fp_m = classify_unmatched_track(tr, golds, matched_tracks)
            fp_reasons[fp_r] += 1
            if len(samples_fp[fp_r]) < 5:
                samples_fp[fp_r].append(
                    {
                        "safe": safe[:48],
                        "track_id": tr["track_id"],
                        "final": {
                            "cat": tr["final_state"].get("chain_category"),
                            "first": tr["final_state"].get("first_event"),
                            "last": tr["final_state"].get("last_event"),
                            "t0_ms": tr["final_state"].get("t0_ms"),
                            "t1_ms": tr["final_state"].get("t1_ms"),
                            "n_states": len(tr["states"]),
                        },
                        **fp_m,
                    }
                )

        for gi, g in enumerate(golds):
            cat = str(g.get("chain_category") or "")
            tpl = templates[gi] or ""
            a_ok = a_matched[gi]
            b_ok = b_ok_list[gi]
            q = ("A✓" if a_ok else "A✗") + ("B✓" if b_ok else "B✗")
            # normalize key
            qkey = {
                "A✓B✓": "A_ok_B_ok",
                "A✓B✗": "A_ok_B_fail",
                "A✗B✓": "A_fail_B_ok",
                "A✗B✗": "A_fail_B_fail",
            }[q]
            quad[qkey] += 1
            quad_by_cat[cat][qkey] += 1
            quad_by_tpl[tpl][qkey] += 1

            if cat in cat_stats:
                cat_stats[cat]["gold"] += 1
                if a_ok:
                    cat_stats[cat]["a_strict"] += 1
                if b_ok:
                    cat_stats[cat]["b_strict"] += 1
            if tpl not in tpl_stats:
                tpl_stats[tpl] = {"gold": 0, "a_strict": 0, "b_strict": 0}
            tpl_stats[tpl]["gold"] += 1
            if a_ok:
                tpl_stats[tpl]["a_strict"] += 1
            if b_ok:
                tpl_stats[tpl]["b_strict"] += 1

            a_reason, a_meta = ("matched", {})
            if not a_ok:
                a_reason, a_meta = a_primary_failure(
                    g,
                    gi=gi,
                    matched=False,
                    assigned_track=a_track_ids[gi],
                    edges_for_gold=edges_by_gold.get(gi, []),
                    matched_map=matched_map,
                    tracks=tracks,
                    full_strip=full_strip,
                )
                a_fail_reasons[a_reason] += 1
                if cat:
                    a_fail_by_cat[cat][a_reason] += 1
                if tpl:
                    a_fail_by_tpl[tpl][a_reason] += 1
                if len(samples_a[a_reason]) < 5:
                    tr = best_overlapping_track(g, tracks)
                    samples_a[a_reason].append(
                        {
                            "safe": safe[:48],
                            "ann": g.get("annotation_id"),
                            "cat": cat,
                            "template": tpl,
                            "gold_events": [e.get("type") for e in (g.get("events") or [])],
                            "gold_t0_t1": [g.get("t0_ms"), g.get("t1_ms")],
                            "a_meta": a_meta,
                            "b_ok": b_ok,
                            "b_pred": b_preds[gi],
                            "b_internal": b_internals[gi].get("primary"),
                            "nearest_track_states": [
                                {
                                    "prefix_t_ms": st["prefix_t_ms"],
                                    "first": st["pred"].get("first_event"),
                                    "last": st["pred"].get("last_event"),
                                    "cat": st["pred"].get("chain_category"),
                                    "t0_ms": st["pred"].get("t0_ms"),
                                    "t1_ms": st["pred"].get("t1_ms"),
                                }
                                for st in ((tr or {}).get("states") or [])[:8]
                            ]
                            if tr
                            else [],
                            "anchor_sliding": {
                                "n_anchor_geom": len(geom_related(g, full_strip.get("anchor_geom") or [])),
                                "n_sliding_geom": len(geom_related(g, full_strip.get("sliding_geom") or [])),
                            },
                        }
                    )

            if not b_ok:
                br = b_internals[gi].get("primary") or "unknown"
                b_fail_reasons[br] += 1
                if len(samples_b[br]) < 5:
                    samples_b[br].append(
                        {
                            "safe": safe[:48],
                            "ann": g.get("annotation_id"),
                            "cat": cat,
                            "template": tpl,
                            "gold_events": [e.get("type") for e in (g.get("events") or [])],
                            "gold_t0_t1": [g.get("t0_ms"), g.get("t1_ms")],
                            "b_detail": b_internals[gi],
                            "a_ok": a_ok,
                        }
                    )

            if a_ok and not b_ok and len(samples_axbx) < 15:
                samples_axbx.append(
                    {
                        "safe": safe[:48],
                        "ann": g.get("annotation_id"),
                        "cat": cat,
                        "template": tpl,
                        "gold_events": [e.get("type") for e in (g.get("events") or [])],
                        "a_track_id": a_track_ids[gi],
                        "b_internal": b_internals[gi],
                        "note": "prefix formed strict chain but oracle slice did not",
                    }
                )

            if (not a_ok) and b_ok:
                ba_r = reason_b_ok_a_fail(
                    g,
                    a_reason=a_reason,
                    a_meta=a_meta,
                    tracks=tracks,
                    b_pred=b_preds[gi],
                    golds=golds,
                    matched_track_ids=matched_track_id_set,
                )
                ba_reasons[ba_r] += 1
                if len(samples_ba[ba_r]) < 5:
                    samples_ba[ba_r].append(
                        {
                            "safe": safe[:48],
                            "ann": g.get("annotation_id"),
                            "cat": cat,
                            "template": tpl,
                            "gold_events": [e.get("type") for e in (g.get("events") or [])],
                            "gold_t0_t1": [g.get("t0_ms"), g.get("t1_ms")],
                            "a_primary": a_reason,
                            "ba_reason": ba_r,
                            "b_pred": b_preds[gi],
                            "a_meta": a_meta,
                        }
                    )

            gold_records.append(
                {
                    "safe_id": safe,
                    "annotation_id": g.get("annotation_id"),
                    "category": cat,
                    "template_id": tpl,
                    "a_ok": a_ok,
                    "b_ok": b_ok,
                    "quadrant": qkey,
                    "a_reason": a_reason if not a_ok else None,
                    "b_reason": None if b_ok else b_internals[gi].get("primary"),
                }
            )

        print(
            f"  A={sum(a_matched)}/{len(golds)} B={sum(b_ok_list)}/{len(golds)} "
            f"tracks={len(tracks)} unmatched={len(unmatched)}",
            flush=True,
        )

    # build template table
    tpl_table = []
    for tid in TEMPLATE_IDS + [""]:
        st = tpl_stats.get(tid) or {"gold": 0, "a_strict": 0, "b_strict": 0}
        if st["gold"] == 0 and tid == "":
            continue
        if st["gold"] == 0:
            continue
        main_fail = ""
        if tid in a_fail_by_tpl and a_fail_by_tpl[tid]:
            main_fail = a_fail_by_tpl[tid].most_common(1)[0][0]
        tpl_table.append(
            {
                "template": tid or "(unclassified)",
                "category": (CHAIN4_TEMPLATES.get(tid) or {}).get("category", ""),
                "gold": st["gold"],
                "a_strict": st["a_strict"],
                "a_rate": _pct(st["a_strict"], st["gold"]),
                "b_strict": st["b_strict"],
                "b_rate": _pct(st["b_strict"], st["gold"]),
                "a_b_gap_pp": round(
                    _pct(st["b_strict"], st["gold"]) - _pct(st["a_strict"], st["gold"]), 2
                ),
                "main_a_fail": main_fail,
            }
        )
    tpl_table.sort(key=lambda x: (-(x["gold"] - x["a_strict"]), -x["gold"]))

    cat_table = []
    for c in CATS:
        st = cat_stats[c]
        main_fail = a_fail_by_cat[c].most_common(1)[0][0] if a_fail_by_cat[c] else ""
        cat_table.append(
            {
                "category": c,
                "gold": st["gold"],
                "a_strict": st["a_strict"],
                "a_rate": _pct(st["a_strict"], st["gold"]),
                "b_strict": st["b_strict"],
                "b_rate": _pct(st["b_strict"], st["gold"]),
                "a_b_gap_pp": round(
                    _pct(st["b_strict"], st["gold"]) - _pct(st["a_strict"], st["gold"]), 2
                ),
                "main_a_fail": main_fail,
                "quad": dict(quad_by_cat[c]),
            }
        )

    n_a_fail = sum(a_fail_reasons.values())
    n_ba = sum(ba_reasons.values())
    n_b_fail = sum(b_fail_reasons.values())
    n_fp = sum(fp_reasons.values())

    report = {
        "config": {
            "stream_source": "gold_events",
            "rule_only": True,
            "match_mode": "bipartite_max_weight_one_to_one",
            "note": "P1 诊断 only；未改 strip/参数/指标/Qwen",
        },
        "baseline": {
            "offline_strict": 90.62,
            "B_strict": 81.46,
            "A_strict": 64.76,
            "A_precision": 87.08,
            "matched_gold": 283,
            "n_tracks": 325,
            "unmatched_tracks_expected": 42,
        },
        "observed_tracks": {
            "n_tracks_total": n_tracks_total,
            "n_matched_tracks": n_matched_tracks,
            "n_unmatched_tracks": n_unmatched_tracks,
        },
        "quadrant": dict(quad),
        "quadrant_by_category": {k: dict(v) for k, v in quad_by_cat.items()},
        "quadrant_by_template": {k: dict(v) for k, v in quad_by_tpl.items() if sum(v.values()) > 0},
        "a_failure_primary": dict(a_fail_reasons),
        "a_failure_n": n_a_fail,
        "a_failure_by_category": {k: dict(v) for k, v in a_fail_by_cat.items()},
        "b_ok_a_fail_reasons": {
            k: {"n": v, "pct": _pct(v, n_ba)} for k, v in ba_reasons.most_common()
        },
        "b_ok_a_fail_n": n_ba,
        "b_failure_internal": dict(b_fail_reasons),
        "b_failure_n": n_b_fail,
        "unmatched_track_fp": {
            k: {"n": v, "pct": _pct(v, n_fp)} for k, v in fp_reasons.most_common()
        },
        "unmatched_track_n": n_fp,
        "category_table": cat_table,
        "template_table": tpl_table,
        "samples": {
            "a_failure": {k: v for k, v in samples_a.items()},
            "b_ok_a_fail": {k: v for k, v in samples_ba.items()},
            "b_failure": {k: v for k, v in samples_b.items()},
            "unmatched_fp": {k: v for k, v in samples_fp.items()},
            "a_ok_b_fail": samples_axbx,
        },
        "gold_rows_slim": gold_records,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    json_path = Path(args.out_json) if args.out_json else OUT / "diag_p1_failure_attribution.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # markdown
    lines = []
    lines.append("# P1 流式拆条失败归因（rule-only + gold_events）\n")
    lines.append("只读诊断；未改 strip / 参数 / 评测指标 / Qwen。\n")
    lines.append("Baseline：offline 90.62% · B 81.46% · A 64.76% · precision 87.08% · matched 283/325 tracks。\n")

    lines.append("## 1. A/B 四象限\n")
    lines.append("| 象限 | 数量 |")
    lines.append("|------|-----:|")
    for k in ("A_ok_B_ok", "A_ok_B_fail", "A_fail_B_ok", "A_fail_B_fail"):
        lines.append(f"| {k} | {quad.get(k, 0)} |")
    lines.append("")
    lines.append("### 按四大类\n")
    lines.append("| category | A✓B✓ | A✓B✗ | A✗B✓ | A✗B✗ |")
    lines.append("|----------|-----:|-----:|-----:|-----:|")
    for c in CATS:
        q = quad_by_cat[c]
        lines.append(
            f"| {c} | {q.get('A_ok_B_ok',0)} | {q.get('A_ok_B_fail',0)} | "
            f"{q.get('A_fail_B_ok',0)} | {q.get('A_fail_B_fail',0)} |"
        )
    lines.append("")
    if quad.get("A_ok_B_fail", 0):
        lines.append(
            f"**注意：存在 A✓B✗ = {quad.get('A_ok_B_fail')}**："
            "prefix 场景形成了严格链，但 oracle slice 上 strip 未严格成功。"
            "样例见 JSON `samples.a_ok_b_fail`。\n"
        )

    lines.append("## 2. A 失败 primary reason（互斥）\n")
    lines.append(f"合计 A✗ = **{n_a_fail}**（期望 ~154）\n")
    lines.append("| reason | n | % |")
    lines.append("|--------|--:|--:|")
    for k, v in a_fail_reasons.most_common():
        lines.append(f"| {k} | {v} | {_pct(v, n_a_fail)} |")
    lines.append("")

    lines.append("## 3. B✓ A✗ 专项\n")
    lines.append(f"合计 **{n_ba}**\n")
    lines.append("| B✓A✗ 原因 | 数量 | 占比 |")
    lines.append("|-----------|-----:|-----:|")
    for k, v in ba_reasons.most_common():
        lines.append(f"| {k} | {v} | {_pct(v, n_ba)}% |")
    lines.append("")

    lines.append("## 4. B 失败 strip 内部\n")
    lines.append(f"合计 B✗ = **{n_b_fail}**\n")
    lines.append("| reason | n |")
    lines.append("|--------|--:|")
    for k, v in b_fail_reasons.most_common():
        lines.append(f"| {k} | {v} |")
    lines.append("")

    lines.append("## 5. Unmatched tracks（FP）\n")
    lines.append(
        f"观测 tracks={n_tracks_total}, matched={n_matched_tracks}, unmatched=**{n_unmatched_tracks}**\n"
    )
    lines.append("| FP 类型 | n | % |")
    lines.append("|--------|--:|--:|")
    for k, v in fp_reasons.most_common():
        lines.append(f"| {k} | {v} | {_pct(v, n_fp)} |")
    lines.append("")

    lines.append("## 6. 四大类 + 模板\n")
    lines.append("### 四大类\n")
    lines.append("| category | gold | A strict | A% | B strict | B% | A-B gap(pp) | 主要 A 失败 |")
    lines.append("|----------|-----:|---------:|---:|---------:|---:|------------:|------------|")
    for row in cat_table:
        lines.append(
            f"| {row['category']} | {row['gold']} | {row['a_strict']} | {row['a_rate']} | "
            f"{row['b_strict']} | {row['b_rate']} | {row['a_b_gap_pp']} | {row['main_a_fail']} |"
        )
    lines.append("\n### 模板（按 A 失败数排序）\n")
    lines.append("| template | gold | A% | B% | A-B gap | 主要失败 |")
    lines.append("|----------|-----:|---:|---:|--------:|----------|")
    for row in tpl_table:
        lines.append(
            f"| {row['template']} | {row['gold']} | {row['a_rate']} | {row['b_rate']} | "
            f"{row['a_b_gap_pp']} | {row['main_a_fail']} |"
        )
    lines.append("")
    lines.append("## 7. 样例\n")
    lines.append("详见 `diag_p1_failure_attribution.json` → `samples`。\n")
    lines.append("\n---\nP1 结束；待确认后再进入 P2。\n")

    md_path = Path(args.out_md) if args.out_md else OUT / "diag_p1_failure_attribution.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", json_path)
    print("wrote", md_path)
    print("quad", dict(quad))
    print("a_fail", dict(a_fail_reasons))
    print("ba", dict(ba_reasons))
    print("b_fail", dict(b_fail_reasons))
    print("fp", dict(fp_reasons))


if __name__ == "__main__":
    main()
