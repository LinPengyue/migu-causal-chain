"""将 10月10日 拆条 JSON 中 is_causal_chain=是 的片段转为 A3 jsonl（供 causal_chain2.test 评测）。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from causal_chain2.a3_schema import SCHEMA_VERSION
from causal_chain2.chain_schema import CHAIN_TEMPLATES, EVENT_TYPES
from causal_chain2.event_io import ensure_event_ids

# 中文事件 type -> 系统 EVENT_TYPES key
ZH_EVENT_TO_TYPE: Dict[str, str] = {zh: en for en, zh in EVENT_TYPES.items()}
ZH_EVENT_TO_TYPE.update(
    {
        "头球": "header_shot",
        "传中": "cross",
        "角球": "corner",
        "点球": "penalty",
        "犯规": "foul",
        "抢断": "successful_tackle",
        "拦截": "interception",
        "扑救": "keeper_save",
        "门线救险": "goal_line_clearance",
        "过人": "dribble_past",
    }
)

# 标注子类型 -> chain_template_id
SUBTYPE_TO_TEMPLATE: Dict[str, str] = {
    "射中门柱/横梁链": "shot_post_bar_chain",
    "门框后二次进攻链": "second_phase_after_frame_chain",
    "门线极限救险链": "goal_line_extreme_save_chain",
    "门将脱手致险链": "keeper_spill_danger_chain",
    "手抛球发动进攻链": "throw_in_build_up_chain",
    "快发定位球链": "quick_restart_set_piece_chain",
}

CAUSAL_TYPE_TO_CATEGORY: Dict[str, str] = {
    "结果链": "outcome",
    "改判链": "correction",
    "险情链": "danger",
    "特殊链": "special",
}


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", s.strip())
    return re.sub(r"_+", "_", s).strip("_")[:48] or "seg"


def _parse_segment_t0_ms(segment_time_range: str) -> Optional[float]:
    """segment_time_range 形如 '1518.712：1528.634'（秒）。"""
    if not segment_time_range:
        return None
    part = str(segment_time_range).split("：")[0].split(":")[0].strip()
    try:
        return float(part) * 1000.0
    except ValueError:
        return None


def _normalize_events(
    raw_events: List[Dict[str, Any]],
    *,
    prefix: str,
    segment_t0_ms: Optional[float],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """转英文 type，t_ms 改为片段内相对毫秒；返回 (normalized, raw, warnings)。"""
    warnings: List[str] = []
    if not raw_events:
        return [], [], ["empty_events"]

    raw_out: List[Dict[str, Any]] = []
    for i, e in enumerate(raw_events):
        raw_out.append(
            {
                "order": i,
                "type": str(e.get("type", "")),
                "t_ms": int(float(e.get("t_ms", 0))),
            }
        )

    typed: List[Dict[str, Any]] = []
    for i, e in enumerate(raw_events):
        zh = str(e.get("type", "")).strip()
        en = ZH_EVENT_TO_TYPE.get(zh)
        if not en:
            warnings.append(f"unknown_event_type:{zh}")
            en = "pass"
        t_raw = float(e.get("t_ms", 0))
        if segment_t0_ms is not None:
            t_ms = int(max(0, round(t_raw - segment_t0_ms)))
        else:
            base = float(raw_events[0].get("t_ms", 0))
            t_ms = int(max(0, round(t_raw - base)))
        typed.append(
            {
                "order": int(e.get("order", i)),
                "type": en,
                "t_ms": t_ms,
            }
        )

    typed.sort(key=lambda x: (x["t_ms"], x["order"]))
    for i, ev in enumerate(typed):
        ev["order"] = i
    normalized = ensure_event_ids(typed, prefix=prefix)
    return normalized, raw_out, warnings


def convert_segment(
    row: Dict[str, Any],
    *,
    seg_index: int,
    match_id: str,
) -> Dict[str, Any]:
    subtype = str(row.get("causal_chain_subtype", "")).strip()
    template_id = SUBTYPE_TO_TEMPLATE.get(subtype)
    if not template_id:
        raise ValueError(f"unknown causal_chain_subtype: {subtype!r}")

    causal_type = str(row.get("causal_chain_type", "")).strip()
    category = CAUSAL_TYPE_TO_CATEGORY.get(causal_type)
    if not category:
        category = CHAIN_TEMPLATES[template_id]["category"]

    seg_t0 = _parse_segment_t0_ms(str(row.get("segment_time_range", "")))
    ann_id = f"oct10_aus_sm_{seg_index:03d}"
    prefix = ann_id

    normalized, raw_events, warnings = _normalize_events(
        list(row.get("events") or []),
        prefix=prefix,
        segment_t0_ms=seg_t0,
    )

    if category != CHAIN_TEMPLATES[template_id]["category"]:
        warnings.append(
            f"category_mismatch:annot={causal_type},template={CHAIN_TEMPLATES[template_id]['category']}"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "annotation_id": ann_id,
        "match_id": match_id,
        "chain_category": category,
        "chain_template_id": template_id,
        "events_raw": raw_events,
        "events_normalized": normalized,
        "validation": {
            "mode": "external_import",
            "tier": "strict",
            "source_file": "10月10日_2025世预赛欧洲区_奥地利VS圣马力诺_国语.json",
            "source_segment_index": seg_index,
            "source_subtype_zh": subtype,
            "source_causal_type_zh": causal_type,
            "caption": row.get("caption", ""),
            "segment_time_range": row.get("segment_time_range", ""),
            "video_time_range": row.get("video_time_range", ""),
            "warnings": warnings,
        },
    }


def convert_file(
    input_path: Path,
    *,
    match_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    rows = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("input must be a JSON array of segments")

    mid = match_id or _slug(
        Path(str(rows[0].get("video_name", input_path.stem))).stem
    )
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(rows):
        if row.get("is_causal_chain") != "是":
            continue
        out.append(convert_segment(row, seg_index=len(out), match_id=mid))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="10月10日拆条因果链 -> A3 jsonl")
    ap.add_argument(
        "--input",
        type=Path,
        default=Path("causal_chain/examples/10月10日_2025世预赛欧洲区_奥地利VS圣马力诺_国语.json"),
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("eval/eval_oct10_austria_sm_causal.jsonl"),
    )
    ap.add_argument(
        "--match-id",
        type=str,
        default="2025世预赛_奥地利VS圣马力诺",
    )
    ap.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="可选：写出转换摘要 JSON",
    )
    args = ap.parse_args()

    records = convert_file(args.input.expanduser().resolve(), match_id=args.match_id)
    if not records:
        raise SystemExit("no causal segments found")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    warn_n = sum(1 for r in records if r["validation"].get("warnings"))
    print(f"converted {len(records)} segments -> {args.out}")
    print(f"records_with_warnings={warn_n}")

    if args.summary:
        summary = {
            "input": str(args.input),
            "output": str(args.out),
            "count": len(records),
            "by_template": {},
            "records": [
                {
                    "annotation_id": r["annotation_id"],
                    "chain_template_id": r["chain_template_id"],
                    "event_types": [e["type"] for e in r["events_normalized"]],
                    "warnings": r["validation"].get("warnings", []),
                    "caption": r["validation"].get("caption", "")[:80],
                }
                for r in records
            ],
        }
        for r in records:
            tid = r["chain_template_id"]
            summary["by_template"][tid] = summary["by_template"].get(tid, 0) + 1
        args.summary.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"summary -> {args.summary}")


if __name__ == "__main__":
    main()
