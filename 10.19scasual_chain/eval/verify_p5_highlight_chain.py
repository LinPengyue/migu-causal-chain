#!/usr/bin/env python3
"""P5 smoke：1~2 场 strip_gold → highlight_chain。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "algo"))
sys.path.insert(0, str(ROOT / "eval"))

from causal_chain8.link_strip_chains import build_match_highlight_chain  # noqa: E402

NODE_KEYS = {
    "strip_chain_id",
    "t0_ms",
    "t1_ms",
    "chain_category",
    "template_id",
    "first_event",
    "last_event",
    "events",
}
EDGE_KEYS = {"src", "dst", "rel", "score", "reason"}
RELS = {"follow", "same_sequence", "correction_of"}


def _load_gold(mdir: Path) -> List[Dict[str, Any]]:
    obj = json.loads((mdir / "strip_gold.json").read_text(encoding="utf-8"))
    return obj if isinstance(obj, list) else list(obj.get("chains") or [])


def _schema_ok(doc: Dict[str, Any]) -> List[str]:
    issues: List[str] = []
    for k in ("match_id", "nodes", "edges", "highlight_chain", "stats"):
        if k not in doc:
            issues.append(f"missing {k}")
    hc = doc.get("highlight_chain") or {}
    if "ordering" not in hc or "steps" not in hc:
        issues.append("highlight_chain missing ordering/steps")
    for i, n in enumerate(doc.get("nodes") or []):
        miss = NODE_KEYS - set(n.keys())
        if miss:
            issues.append(f"node[{i}] missing {sorted(miss)}")
    for i, e in enumerate(doc.get("edges") or []):
        miss = EDGE_KEYS - set(e.keys())
        if miss:
            issues.append(f"edge[{i}] missing {sorted(miss)}")
        if e.get("rel") not in RELS:
            issues.append(f"edge[{i}] bad rel={e.get('rel')}")
    ordering = list((hc.get("ordering") or []))
    node_ids = [n["strip_chain_id"] for n in (doc.get("nodes") or [])]
    if ordering and set(ordering) != set(node_ids):
        issues.append("ordering id set != nodes id set")
    if doc.get("stats", {}).get("ordering_method") != "graph_topo_from_relations":
        issues.append("ordering_method not graph_topo")
    return issues


def main() -> None:
    index = json.loads((ROOT / "datasets" / "index.json").read_text(encoding="utf-8"))
    # 1) 多链场 2) 含 correction/var 场
    pick_keys = [
        "01_1_9月29日_25-26赛季西甲第7轮_巴塞罗那VS皇家社会",
        "2022-11-29_巴西vs瑞士",
    ]
    chosen = []
    for key in pick_keys:
        for meta in index["matches"]:
            if key in meta["safe_id"]:
                chosen.append(meta)
                break

    report: Dict[str, Any] = {"matches": [], "smoke_pass": False}
    all_ok = True
    for meta in chosen:
        mdir = ROOT / meta["dir"]
        chains = _load_gold(mdir)
        doc = build_match_highlight_chain(
            chains, match_id=meta["safe_id"], source="strip_gold"
        )
        issues = _schema_ok(doc)
        corr_edges = [e for e in doc["edges"] if e["rel"] == "correction_of"]
        row = {
            "safe_id": meta["safe_id"],
            "n_strip": len(chains),
            "n_nodes": len(doc["nodes"]),
            "n_edges": len(doc["edges"]),
            "rel_counts": doc["stats"]["rel_counts"],
            "has_single_highlight_chain": bool(doc.get("highlight_chain", {}).get("ordering")),
            "n_correction_of": len(corr_edges),
            "correction_edges": corr_edges,
            "ordering_head": doc["highlight_chain"]["ordering"][:5],
            "schema_issues": issues,
            "schema_ok": not issues,
        }
        # 多链应合成一条 ordering
        if len(chains) >= 2 and len(doc["highlight_chain"]["ordering"]) != len(chains):
            row["schema_issues"].append("ordering length != n_strip")
            row["schema_ok"] = False
        if "巴西" in meta["safe_id"] and len(corr_edges) < 1:
            row["schema_issues"].append("expected >=1 correction_of on Brazil-Swiss")
            row["schema_ok"] = False
        # 叙事方向：src=原结果，dst=修正
        for e in corr_edges:
            if e.get("reason") not in ("result_then_correction", "correction_links_prior_result"):
                pass
            # 新语义：dst 应为修正侧
            # 仅检查 ordering 中 src 在 dst 前
            ord_map = {cid: i for i, cid in enumerate(doc["highlight_chain"]["ordering"])}
            if ord_map.get(e["src"], 0) >= ord_map.get(e["dst"], 0):
                row["schema_issues"].append(f"correction order bad {e['src']} !before {e['dst']}")
                row["schema_ok"] = False
            if e.get("reason") == "correction_links_prior_result":
                row["schema_issues"].append("legacy correction_of direction still present")
                row["schema_ok"] = False
        all_ok = all_ok and row["schema_ok"]
        report["matches"].append(row)
        # 落盘样例
        outp = ROOT / "reports" / f"p5_highlight_{meta['safe_id'][:40].replace('/', '_')}.json"
        outp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        row["out"] = str(outp.relative_to(ROOT))
        print(json.dumps(row, ensure_ascii=False), flush=True)

    report["smoke_pass"] = bool(all_ok and report["matches"])
    # schema 示例取第二场（含 correction）或第一场
    sample = None
    for meta, row in zip(chosen, report["matches"]):
        p = ROOT / row["out"]
        sample = json.loads(p.read_text(encoding="utf-8"))
        if row["n_correction_of"] > 0:
            break
    report["schema_example"] = {
        "match_id": (sample or {}).get("match_id"),
        "stats": (sample or {}).get("stats"),
        "edges_sample": ((sample or {}).get("edges") or [])[:5],
        "highlight_chain": (sample or {}).get("highlight_chain"),
        "node0": ((sample or {}).get("nodes") or [None])[0],
    }
    out = ROOT / "reports" / "verify_p5_highlight_chain.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n==== P5 smoke ====", flush=True)
    print(
        json.dumps(
            {
                "smoke_pass": report["smoke_pass"],
                "n_matches": len(report["matches"]),
                "per_match": [
                    {
                        "safe_id": m["safe_id"][:48],
                        "n_nodes": m["n_nodes"],
                        "rel_counts": m["rel_counts"],
                        "n_correction_of": m["n_correction_of"],
                        "schema_ok": m["schema_ok"],
                    }
                    for m in report["matches"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    print(f"wrote {out.relative_to(ROOT)}", flush=True)
    sys.exit(0 if report["smoke_pass"] else 1)


if __name__ == "__main__":
    main()
