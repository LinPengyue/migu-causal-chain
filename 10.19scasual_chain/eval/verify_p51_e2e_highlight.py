#!/usr/bin/env python3
"""P5.1：event stream → causal_chain6 strip → chain graph → highlight_chain 联调 smoke。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "algo"))
sys.path.insert(0, str(ROOT / "eval"))

from causal_chain6.config import load_profile  # noqa: E402
from causal_chain6.strip_pipeline import run_strip_highlights_events  # noqa: E402
from causal_chain8.link_strip_chains import build_match_highlight_chain  # noqa: E402


def _load_timeline(mdir: Path) -> List[Dict[str, Any]]:
    raw = json.loads((mdir / "timeline.json").read_text(encoding="utf-8"))
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


def _strip_cfg(profile: Dict[str, Any]) -> Dict[str, Any]:
    s = profile.get("strip") or {}
    return {
        "pre_ms": int(s.get("pre_ms", 120_000)),
        "post_ms": int(s.get("post_ms", 60_000)),
        "window_ms": int(s.get("window_ms", 180_000)),
        "step_ms": int(s.get("step_ms", 90_000)),
        "min_margin": float(s.get("min_margin", 0.08)),
        "min_prob_top1": float(s.get("min_prob_top1", 0.0)),
        "iou_dedupe_thresh": float(s.get("iou_dedupe", 0.5)),
        "iou_recall_thresh": float(s.get("iou_recall", 0.45)),
        "max_events": int(s.get("max_events", 12)),
        "use_sliding_recall": True,
        "template_whitelist": None,
        "sliding_merge_mode": str(s.get("sliding_merge_mode", "none") or "none"),
        "sliding_post_nms": str(s.get("sliding_post_nms", "off") or "off"),
    }


def _run_strip(events: List[Dict[str, Any]], *, match_id: str, profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    cfg = _strip_cfg(profile)
    out = run_strip_highlights_events(
        events=events,
        match_id=match_id,
        profile=profile,
        model=None,
        processor=None,
        device="cpu",
        max_new_tokens=512,
        input_file=f"timeline:{match_id}",
        **cfg,
    )
    return list(out.get("clips") or [])


def _node_sig(n: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        n.get("strip_chain_id"),
        int(n.get("t0_ms") or 0),
        int(n.get("t1_ms") or 0),
        str(n.get("template_id") or ""),
        str(n.get("chain_category") or ""),
    )


def _check_correction_order(
    doc: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """原事件在前、修正链在后；边方向 src=原, dst=修。"""
    order = {cid: i for i, cid in enumerate(doc["highlight_chain"]["ordering"])}
    nodes = {n["strip_chain_id"]: n for n in doc["nodes"]}
    issues = []
    for e in doc["edges"]:
        if e["rel"] != "correction_of":
            continue
        src, dst = e["src"], e["dst"]
        row = {
            "edge": e,
            "src_pos": order.get(src),
            "dst_pos": order.get(dst),
            "src_cat": (nodes.get(src) or {}).get("chain_category"),
            "dst_cat": (nodes.get(dst) or {}).get("chain_category"),
            "src_last": (nodes.get(src) or {}).get("last_event"),
            "dst_last": (nodes.get(dst) or {}).get("last_event"),
            "ok_order": order.get(src, -1) < order.get(dst, -1),
            "ok_edge_dir": True,  # 约定 src=原 dst=修
        }
        # dst 应更像修正（var/disallowed/controversy 或 category correction）
        dst_ev = {(x.get("type") or "") for x in ((nodes.get(dst) or {}).get("events") or [])}
        if not (
            (nodes.get(dst) or {}).get("chain_category") == "correction"
            or dst_ev & {"var", "disallowed_goal", "controversy"}
        ):
            row["ok_edge_dir"] = False
            row["dir_note"] = "dst_not_correction_like"
        if not row["ok_order"]:
            row["order_note"] = "correction_before_original"
        issues.append(row)
    return issues


def main() -> None:
    index = json.loads((ROOT / "datasets" / "index.json").read_text(encoding="utf-8"))
    pick = [
        "2022-11-28_西班牙vs德国",
        "10月20日_25-26赛季西甲第9轮_莱万特VS巴列卡诺",  # strip 产出 correction_of
        "2022-11-30_突尼斯vs法国",
        "01_1_9月29日_25-26赛季西甲第7轮_巴塞罗那VS皇家社会",
        "10月15日_2025世预赛欧洲区_安道尔VS塞尔维亚",
    ]
    metas = []
    for key in pick:
        for m in index["matches"]:
            if key in m["safe_id"]:
                metas.append(m)
                break
    metas = metas[:5]

    profile = dict(load_profile("production"))
    profile.setdefault("llm", {})
    profile["llm"] = dict(profile.get("llm") or {})
    profile["llm"]["enabled"] = False

    rows = []
    any_loss = False
    any_dup = False
    any_order_unstable = False
    any_corr_bad = False

    for meta in metas:
        mdir = ROOT / meta["dir"]
        mid = meta["safe_id"]
        events = _load_timeline(mdir)
        print(f"strip {mid[:48]} n_events={len(events)}", flush=True)
        clips = _run_strip(events, match_id=mid[:32], profile=profile)
        clip_ids = [c.get("proposal_id") or c.get("clip_id") or "" for c in clips]

        doc1 = build_match_highlight_chain(clips, match_id=mid, source="causal_chain6_strip")
        doc2 = build_match_highlight_chain(clips, match_id=mid, source="causal_chain6_strip")

        node_ids = [n["strip_chain_id"] for n in doc1["nodes"]]
        dup = len(node_ids) != len(set(node_ids))
        lost = set(clip_ids) - set(node_ids)
        extra = set(node_ids) - set(clip_ids)
        # clip 无 proposal 时 normalize 可能改名；用数量+时间签名兜底
        clip_sigs = {
            (int(c.get("t0_ms") or 0), int(c.get("t1_ms") or 0), str(c.get("pred_chain_template_id") or ""))
            for c in clips
        }
        node_sigs = {
            (int(n.get("t0_ms") or 0), int(n.get("t1_ms") or 0), str(n.get("template_id") or ""))
            for n in doc1["nodes"]
        }
        loss_by_sig = clip_sigs - node_sigs
        extra_by_sig = node_sigs - clip_sigs
        stable = doc1["highlight_chain"]["ordering"] == doc2["highlight_chain"]["ordering"]
        corr_chk = _check_correction_order(doc1)
        corr_bad = [r for r in corr_chk if not r["ok_order"] or not r["ok_edge_dir"]]

        any_dup = any_dup or dup
        any_loss = any_loss or bool(loss_by_sig) or (len(node_ids) != len(clips))
        any_order_unstable = any_order_unstable or (not stable)
        any_corr_bad = any_corr_bad or bool(corr_bad)

        rel = doc1["stats"]["rel_counts"]
        row = {
            "safe_id": mid,
            "n_events": len(events),
            "n_strip_clips": len(clips),
            "n_nodes": len(node_ids),
            "nodes_dup": dup,
            "nodes_count_match": len(node_ids) == len(clips),
            "lost_sigs": sorted(loss_by_sig)[:5],
            "extra_sigs": sorted(extra_by_sig)[:5],
            "rel_counts": rel,
            "ordering_stable": stable,
            "ordering": doc1["highlight_chain"]["ordering"],
            "n_correction_of": rel.get("correction_of", 0),
            "correction_checks": corr_chk,
            "correction_ok": not corr_bad,
        }
        rows.append(row)
        print(
            json.dumps(
                {
                    "safe_id": mid[:48],
                    "n_clips": len(clips),
                    "n_nodes": len(node_ids),
                    "rel": rel,
                    "dup": dup,
                    "count_match": row["nodes_count_match"],
                    "stable": stable,
                    "corr_ok": row["correction_ok"],
                    "corr": [
                        {
                            "src": c["edge"]["src"],
                            "dst": c["edge"]["dst"],
                            "ok_order": c["ok_order"],
                            "src_pos": c["src_pos"],
                            "dst_pos": c["dst_pos"],
                        }
                        for c in corr_chk
                    ],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    report = {
        "n_matches": len(rows),
        "correction_of_semantics": {
            "edge": "src=original_result, dst=correction_chain",
            "narrative": "src before dst (unified with follow/same_sequence)",
            "fixed_from": "src=correction,dst=result + topo special-case",
        },
        "issues": {
            "nodes_dup": any_dup,
            "nodes_loss": any_loss,
            "ordering_unstable": any_order_unstable,
            "correction_order_bad": any_corr_bad,
        },
        "smoke_pass": not (any_dup or any_loss or any_order_unstable or any_corr_bad),
        "matches": rows,
    }
    out = ROOT / "reports" / "verify_p51_e2e_highlight.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n==== P5.1 ====", flush=True)
    print(
        json.dumps(
            {
                "smoke_pass": report["smoke_pass"],
                "issues": report["issues"],
                "correction_of_semantics": report["correction_of_semantics"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    print(f"wrote {out}", flush=True)
    sys.exit(0 if report["smoke_pass"] else 1)


if __name__ == "__main__":
    main()
