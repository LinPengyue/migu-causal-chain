"""导出 10月10日 *_causal.json（v2 / 1.0-min）标注问题清单 xlsx + csv。"""

from __future__ import annotations

import csv
import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

from causal_chain2.agent_tools import global_rule_shortlist
from causal_chain2.chain_rules import CANONICAL_SEQUENCES, consecutive_pairs_allowed, sequence_matches_template
from causal_chain2.chain_schema import CHAIN_TEMPLATES

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "scripts"))
from convert_oct10_causal_min_to_a3 import (
    CAT_ZH_TO_EN,
    LABEL_ZH_TO_TEMPLATE,
    ZH_EVENT_TO_TYPE,
    _map_event_type,
    load_causal_rows,
)

DEFAULT_SRC = ROOT / "causal_chain/examples/10月10日_2025世预赛欧洲区_奥地利VS圣马力诺_国语_causal.json"
DEFAULT_XLSX = ROOT / "eval/oct10_austria_sm_causal_v2_标注问题清单.xlsx"
DEFAULT_CSV = ROOT / "eval/oct10_austria_sm_causal_v2_标注问题清单.csv"

TEMPLATE_TO_LABEL = {tid: meta["label_zh"] for tid, meta in CHAIN_TEMPLATES.items()}
TEMPLATE_TO_LABEL["outcome_other"] = "其他"

COLUMNS = [
    "序号",
    "annotation_id",
    "match_id",
    "因果链大类(中文)",
    "因果链模版(中文)",
    "系统template_id",
    "系统大类(category)",
    "典型骨架(CANONICAL)",
    "当前事件(中文)",
    "当前事件(英文)",
    "事件数",
    "转移规则合法",
    "CANONICAL完全一致",
    "规则top1预测",
    "规则与标签一致",
    "片段时间(segment_time_sketch)",
    "问题说明",
    "修改建议",
]


def _en_types(events: list[dict]) -> list[str]:
    return [_map_event_type(e, []) for e in events]


def _zh_types(events: list[dict]) -> list[str]:
    return [str(e.get("type", "")) for e in events]


def _rule_top1(types_en: list[str]) -> str:
    ranked = global_rule_shortlist(types_en, top_k=1)
    return ranked[0]["chain_template_id"] if ranked else ""


def _suggest(
    *,
    label_zh: str,
    cat_zh: str,
    template_id: str,
    types_en: list[str],
    types_zh: list[str],
    rule_pred: str,
    trans_ok: bool,
    exact_ok: bool,
) -> tuple[str, str]:
    issues: list[str] = []
    fixes: list[str] = []

    if not trans_ok:
        issues.append("事件序列不符合该模版的转移规则")
    if not exact_ok:
        if not issues:
            issues.append("事件序列与典型骨架(CANONICAL)不一致")

    if template_id == "outcome_other":
        if rule_pred and rule_pred != "outcome_other":
            issues.append(
                f"标「其他」但规则更倾向「{TEMPLATE_TO_LABEL.get(rule_pred, rule_pred)}」"
            )
            fixes.append(f"建议改标：{TEMPLATE_TO_LABEL.get(rule_pred, rule_pred)}")
        if types_en == ["shot", "goal"]:
            fixes.append("或明确保留「其他」：需在标注规范中定义何时用其他 vs 折射进球")
        if types_en == ["pass", "pass", "shot", "goal"]:
            fixes.append("建议改标：角球传中进球链；补事件：角球/传中/头球射门")

    if template_id == "turnover_counter_goal":
        if not any(t in types_en for t in ("successful_tackle", "interception", "possession_lost")):
            issues.append("标反击/抢断进球链但无抢断/拦截/丢球事件")
            if types_en in (["pass", "goal"], ["pass", "shot", "goal"]):
                fixes.append("改标：其他（进球）；或补前置：抢断成功/拦截")
            elif rule_pred == "outcome_other":
                fixes.append("建议改标：其他（进球）")

    if template_id == "goal_disallowed_chain":
        if "var" not in types_en and "disallowed_goal" not in types_en:
            issues.append("标进球无效链但缺少 VAR / 无效进球 事件")
            fixes.append("补事件：争议→VAR→disallowed_goal；或改标")

    if template_id == "shot_save_chain":
        if "keeper_save" not in types_en:
            issues.append("标射门扑救链但无门将扑救事件")
            fixes.append("补事件：keeper_save(扑救)；或改标")
        elif len(types_en) > 4:
            issues.append("事件链过长，含大量传球/控球，不像典型射门扑救链")
            fixes.append("精简为 pass/cross→shot→keeper_save；或改标角球/反击类")
        elif rule_pred == "corner_cross_goal":
            fixes.append("规则更像角球传中进球链：补角球/传中，或改标")
        elif rule_pred not in ("shot_save_chain", template_id):
            fixes.append(
                f"规则预测为「{TEMPLATE_TO_LABEL.get(rule_pred, rule_pred)}」，请核对模版"
            )

    if template_id == "corner_cross_goal":
        if "corner" not in types_en and "cross" not in types_en:
            issues.append("标角球传中进球链但无角球/传中事件")
            fixes.append("补事件：角球、传中；或改标")

    if template_id == "goal_line_extreme_save_chain":
        if types_en == ["pass", "shot", "goal_line_clearance"]:
            issues.append("含传球→射门→门线救险，与典型 shot→门线救险 不一致")
            fixes.append("确认是否应为门线救险；补/改事件序列")

    if template_id == "keeper_spill_danger_chain" and types_en == ["shot", "keeper_save"]:
        issues.append("标脱手链但只有射门→扑救，缺脱手后第二脚射门")
        fixes.append("改标：射门扑救链；或补第三事件：射门")

    for zh in types_zh:
        if zh not in ZH_EVENT_TO_TYPE:
            issues.append(f"非标准事件类型：{zh}")
            fixes.append("改用34类标准事件名（见 chain_schema.EVENT_TYPES）")

    cat_en = CAT_ZH_TO_EN.get(cat_zh, "")
    if cat_en and template_id and CHAIN_TEMPLATES.get(template_id):
        if cat_en != CHAIN_TEMPLATES[template_id]["category"]:
            issues.append(
                f"大类不一致：标注={cat_zh}，模版系统大类={CHAIN_TEMPLATES[template_id]['category']}"
            )

    if rule_pred and rule_pred != template_id and template_id != "outcome_other":
        if not any("规则" in x for x in issues):
            issues.append(
                f"规则top1为「{TEMPLATE_TO_LABEL.get(rule_pred, rule_pred)}」，与当前标签不一致"
            )
            if not fixes:
                fixes.append(f"建议核对改标为：{TEMPLATE_TO_LABEL.get(rule_pred, rule_pred)}")

    if not issues:
        issues.append("相对合理（建议复核）")
        if not fixes:
            fixes.append("可保留")

    return "；".join(dict.fromkeys(issues)), "；".join(dict.fromkeys(fixes))


def build_rows(src_path: Path) -> list[dict[str, str]]:
    rows_raw, _meta = load_causal_rows(src_path)
    seq_label_map: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for r in rows_raw:
        types_en = tuple(_en_types(r.get("events") or []))
        label = str(r.get("chain_template_id", ""))
        tid = LABEL_ZH_TO_TEMPLATE.get(label, "")
        if tid:
            seq_label_map[types_en].add(label)

    out: list[dict[str, str]] = []
    for i, r in enumerate(rows_raw):
        label_zh = str(r.get("chain_template_id", ""))
        cat_zh = str(r.get("chain_category", ""))
        template_id = LABEL_ZH_TO_TEMPLATE.get(label_zh, "")
        events = list(r.get("events") or [])
        types_zh = _zh_types(events)
        types_en = _en_types(events)
        canonical = CANONICAL_SEQUENCES.get(template_id, [])
        trans_ok = bool(template_id and consecutive_pairs_allowed(template_id, types_en))
        exact_ok = bool(template_id and sequence_matches_template(template_id, types_en))
        rule_pred = _rule_top1(types_en) if types_en else ""
        rule_match = "是" if rule_pred == template_id else "否"
        issue, fix = _suggest(
            label_zh=label_zh,
            cat_zh=cat_zh,
            template_id=template_id,
            types_en=types_en,
            types_zh=types_zh,
            rule_pred=rule_pred,
            trans_ok=trans_ok,
            exact_ok=exact_ok,
        )
        seq_key = tuple(types_en)
        if len(seq_label_map.get(seq_key, set())) > 1:
            alts = " / ".join(sorted(seq_label_map[seq_key]))
            issue += f"；同序列多种标签({alts})"
            fix += f"；统一序列「{'→'.join(types_zh)}」的标签"

        cat_en = CAT_ZH_TO_EN.get(cat_zh, CHAIN_TEMPLATES.get(template_id, {}).get("category", ""))
        out.append(
            {
                "序号": str(i + 1),
                "annotation_id": str(r.get("annotation_id", "")),
                "match_id": str(r.get("match_id", "")),
                "因果链大类(中文)": cat_zh,
                "因果链模版(中文)": label_zh,
                "系统template_id": template_id,
                "系统大类(category)": cat_en,
                "典型骨架(CANONICAL)": " | ".join("→".join(s) for s in canonical[:2]),
                "当前事件(中文)": " → ".join(types_zh) if types_zh else "(空)",
                "当前事件(英文)": " → ".join(types_en) if types_en else "(空)",
                "事件数": str(len(events)),
                "转移规则合法": "是" if trans_ok else "否",
                "CANONICAL完全一致": "是" if exact_ok else "否",
                "规则top1预测": TEMPLATE_TO_LABEL.get(rule_pred, rule_pred),
                "规则与标签一致": rule_match,
                "片段时间(segment_time_sketch)": str(r.get("segment_time_sketch", "")),
                "问题说明": issue,
                "修改建议": fix,
            }
        )
    return out


def write_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def _col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _sheet_xml(rows: list[dict[str, str]], headers: list[str]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        "<sheetData>",
    ]
    r_idx = 1

    def row_xml(values: list[str]) -> str:
        nonlocal r_idx
        cells = []
        for c_idx, val in enumerate(values, 1):
            ref = f"{_col_letter(c_idx)}{r_idx}"
            text = escape(str(val))
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>')
        r_idx += 1
        return f'<row r="{r_idx - 1}">' + "".join(cells) + "</row>"

    lines.append(row_xml(headers))
    for row in rows:
        lines.append(row_xml([row[h] for h in headers]))
    lines.extend(["</sheetData>", "</worksheet>"])
    return "\n".join(lines)


def _summary_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    n = len(rows)
    trans_bad = sum(1 for r in rows if r["转移规则合法"] == "否")
    exact_bad = sum(1 for r in rows if r["CANONICAL完全一致"] == "否")
    rule_bad = sum(1 for r in rows if r["规则与标签一致"] == "否")
    other_n = sum(1 for r in rows if r["系统template_id"] == "outcome_other")
    tmpl = Counter(r["因果链模版(中文)"] for r in rows)
    summary = [
        {"统计项": "总条数", "数值": str(n), "说明": ""},
        {"统计项": "转移规则不合法", "数值": str(trans_bad), "说明": f"{trans_bad/n:.1%}"},
        {"统计项": "CANONICAL不一致", "数值": str(exact_bad), "说明": f"{exact_bad/n:.1%}"},
        {"统计项": "规则top1与标签不一致", "数值": str(rule_bad), "说明": f"{rule_bad/n:.1%}"},
        {"统计项": "标「其他」条数", "数值": str(other_n), "说明": f"{other_n/n:.1%}"},
    ]
    for label, cnt in tmpl.most_common():
        summary.append({"统计项": f"模版:{label}", "数值": str(cnt), "说明": ""})
    return summary


def write_xlsx(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = _summary_rows(rows)
    summary_headers = ["统计项", "数值", "说明"]
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    wb_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
</Relationships>"""
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="标注问题清单" sheetId="1" r:id="rId1"/>
    <sheet name="问题汇总" sheetId="2" r:id="rId2"/>
  </sheets>
</workbook>"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/worksheets/sheet1.xml", _sheet_xml(rows, COLUMNS))
        z.writestr("xl/worksheets/sheet2.xml", _sheet_xml(summary, summary_headers))


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="导出 v2 causal.json 标注问题清单")
    ap.add_argument("--input", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX)
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    args = ap.parse_args()

    rows = build_rows(args.input.expanduser().resolve())
    write_csv(rows, args.csv)
    write_xlsx(rows, args.xlsx)
    bad = sum(1 for r in rows if r["转移规则合法"] == "否" or r["规则与标签一致"] == "否")
    print(f"wrote {args.xlsx}")
    print(f"wrote {args.csv}")
    print(f"rows={len(rows)}  need_review>={bad}")


if __name__ == "__main__":
    main()
