"""将 1.0-min causal JSON（数组或 causal_chains 包装）转为 A3 jsonl。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from causal_chain2.a3_schema import SCHEMA_VERSION
from causal_chain2.chain_schema import CHAIN_TEMPLATES, EVENT_TYPES
from causal_chain2.event_io import ensure_event_ids

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
        "防守动作": "successful_tackle",
        "犯规/被犯规": "fouled",
        "控球": "pass",
    }
)

EN_EVENT_TO_TYPE: Dict[str, str] = {
    "pass": "pass",
    "shot": "shot",
    "goal": "goal",
    "save": "keeper_save",
    "throw_in": "throw_in",
    "corner_kick": "corner",
    "free_kick": "free_kick",
    "goal_line_clearance": "goal_line_clearance",
    "dribble_past": "dribble_past",
    "defensive_action": "successful_tackle",
    "ball_possession": "pass",
    "assist": "assist",
    "win_an_aerial_duel": "aerial_won",
    "header": "header_shot",
    "cross": "cross",
    "foul": "foul",
    "var": "var",
}

LABEL_ZH_TO_TEMPLATE: Dict[str, str] = {
    meta["label_zh"]: tid for tid, meta in CHAIN_TEMPLATES.items()
}
LABEL_ZH_TO_TEMPLATE.update(
    {
        "其他": "outcome_other",
        "抢断/反击/失误后直接进球链": "turnover_counter_goal",
        "抢断/反击/失误造成进球链": "turnover_counter_goal",
        "射门扑救链": "shot_save_chain",
        "角球传中进球链": "corner_cross_goal",
        "进球无效链": "goal_disallowed_chain",
        "射中门柱/横梁链": "shot_post_bar_chain",
        "门线极限救险链": "goal_line_extreme_save_chain",
        "门框后二次进攻链": "second_phase_after_frame_chain",
        "门将脱手致险链": "keeper_spill_danger_chain",
        "手抛球发动进攻链": "throw_in_build_up_chain",
        "快发定位球链": "quick_restart_set_piece_chain",
        "折射/变线进球链": "deflection_goal_chain",
        "折射/变线入网链": "deflection_goal_chain",
    }
)

CAT_ZH_TO_EN = {
    "结果链": "outcome",
    "改判链": "correction",
    "修正链": "correction",
    "险情链": "danger",
    "特殊链": "special",
}


def _map_event_type(ev: Dict[str, Any], warnings: List[str]) -> str:
    zh = str(ev.get("type", "")).strip()
    params = ev.get("params") or {}
    tag = str(params.get("Type", "")).strip().lower()
    if tag == "cross" and zh in ("传球", ""):
        return "cross"

    if zh in ZH_EVENT_TO_TYPE:
        en = ZH_EVENT_TO_TYPE[zh]
        if zh == "控球":
            warnings.append("mapped_ball_possession_to_pass")
        return en

    type_en = str(ev.get("type_en", "")).strip()
    if type_en:
        key = re.sub(r"[^a-z0-9]+", "_", type_en.lower()).strip("_")
        if key in EN_EVENT_TO_TYPE:
            en = EN_EVENT_TO_TYPE[key]
            if key == "ball_possession":
                warnings.append("mapped_ball_possession_to_pass")
            return en

    if tag in ("corner_kick", "corner"):
        return "corner"

    warnings.append(f"unknown_event_type:{zh or type_en}")
    return "pass"


def _normalize_events(
    raw_events: List[Dict[str, Any]],
    *,
    prefix: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    warnings: List[str] = []
    if not raw_events:
        return [], [], ["empty_events"]

    raw_out: List[Dict[str, Any]] = []
    for i, e in enumerate(raw_events):
        raw_out.append(
            {
                "order": int(e.get("order", i)),
                "type": str(e.get("type", "")),
                "t_ms": int(float(e.get("t_ms", 0))),
            }
        )

    base = float(raw_events[0].get("t_ms", 0))
    typed: List[Dict[str, Any]] = []
    for i, e in enumerate(raw_events):
        en = _map_event_type(e, warnings)
        t_ms = int(max(0, round(float(e.get("t_ms", 0)) - base)))
        typed.append({"order": int(e.get("order", i)), "type": en, "t_ms": t_ms})

    typed.sort(key=lambda x: (x["t_ms"], x["order"]))
    for i, ev in enumerate(typed):
        ev["order"] = i
    normalized = ensure_event_ids(typed, prefix=prefix)
    return normalized, raw_out, warnings


def load_causal_rows(path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """支持根为数组，或含 causal_chains 的对象。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw, {}

    if isinstance(raw, dict) and "causal_chains" in raw:
        meta = {k: v for k, v in raw.items() if k != "causal_chains"}
        rows: List[Dict[str, Any]] = []
        for chain in raw["causal_chains"]:
            row = dict(chain)
            row.setdefault("match_id", meta.get("match_id", path.stem))
            row.setdefault("schema_version", meta.get("schema_version", "1.0-min"))
            row["_meta"] = meta
            rows.append(row)
        return rows, meta

    raise ValueError("input must be a JSON array or an object with causal_chains")


def convert_record(
    row: Dict[str, Any],
    *,
    index: int,
    source_file: str,
    default_match_id: str,
) -> Dict[str, Any]:
    label = str(row.get("chain_template_id", "")).strip()
    template_id = LABEL_ZH_TO_TEMPLATE.get(label)
    if not template_id:
        raise ValueError(f"unknown chain_template_id label: {label!r}")

    cat_zh = str(row.get("chain_category", "")).strip()
    category = CAT_ZH_TO_EN.get(cat_zh)
    if not category:
        category = CHAIN_TEMPLATES[template_id]["category"]

    ann_id = str(row.get("annotation_id") or f"causal_{index:04d}")
    prefix = ann_id.replace("/", "_")[:32]
    normalized, raw_events, warnings = _normalize_events(
        list(row.get("events") or []), prefix=prefix
    )

    if category != CHAIN_TEMPLATES[template_id]["category"]:
        warnings.append(
            f"category_mismatch:annot={cat_zh},template={CHAIN_TEMPLATES[template_id]['category']}"
        )

    validation: Dict[str, Any] = {
        "mode": "external_import",
        "tier": "strict",
        "source_file": source_file,
        "source_label_zh": label,
        "source_category_zh": cat_zh,
        "schema_version_src": row.get("schema_version", ""),
        "warnings": warnings,
    }
    for key in ("bz_id", "segment_time_sketch", "segment_time_video", "is_replay"):
        if row.get(key):
            validation[key] = row[key]

    return {
        "schema_version": SCHEMA_VERSION,
        "annotation_id": ann_id,
        "match_id": str(row.get("match_id") or default_match_id),
        "chain_category": category,
        "chain_template_id": template_id,
        "events_raw": raw_events,
        "events_normalized": normalized,
        "validation": validation,
    }


def convert_file(input_path: Path) -> List[Dict[str, Any]]:
    rows, meta = load_causal_rows(input_path)
    default_match_id = str(meta.get("match_id") or input_path.stem)
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(rows):
        out.append(
            convert_record(
                row,
                index=i,
                source_file=input_path.name,
                default_match_id=default_match_id,
            )
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="causal JSON（1.0-min）-> A3 jsonl")
    ap.add_argument(
        "--input",
        type=Path,
        required=True,
    )
    ap.add_argument(
        "--out",
        type=Path,
        required=True,
    )
    args = ap.parse_args()
    input_path = args.input.expanduser().resolve()
    records = convert_file(input_path)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    warn_n = sum(1 for r in records if r["validation"].get("warnings"))
    print(f"converted {len(records)} -> {args.out}")
    print(f"records_with_warnings={warn_n}")


if __name__ == "__main__":
    main()
