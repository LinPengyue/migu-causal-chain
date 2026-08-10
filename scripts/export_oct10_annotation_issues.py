"""导出 10月10日因果链标注问题清单（xlsx + csv，无第三方依赖）。"""

from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from causal_chain2.chain_rules import CANONICAL_SEQUENCES, consecutive_pairs_allowed, sequence_matches_template

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "causal_chain/examples/10月10日_2025世预赛欧洲区_奥地利VS圣马力诺_国语.json"
OUT_XLSX = ROOT / "eval/oct10_austria_sm_标注问题清单.xlsx"
OUT_CSV = ROOT / "eval/oct10_austria_sm_标注问题清单.csv"

SUBTYPE_TO_TEMPLATE = {
    "射中门柱/横梁链": "shot_post_bar_chain",
    "门框后二次进攻链": "second_phase_after_frame_chain",
    "门线极限救险链": "goal_line_extreme_save_chain",
    "门将脱手致险链": "keeper_spill_danger_chain",
    "手抛球发动进攻链": "throw_in_build_up_chain",
    "快发定位球链": "quick_restart_set_piece_chain",
}
ZH = {
    "传球": "pass",
    "射门": "shot",
    "进球": "goal",
    "界外球": "throw_in",
    "门线救险": "goal_line_clearance",
    "任意球": "free_kick",
    "扑救": "keeper_save",
    "过人": "dribble_past",
}

COLUMNS = [
    "序号",
    "评测ID",
    "片段时间段(segment_time_range)",
    "视频时间(video_time_range)",
    "因果链大类",
    "因果链子类型",
    "系统template_id",
    "典型骨架(CANONICAL)",
    "当前事件(中文)",
    "当前事件(英文)",
    "转移规则合法",
    "CANONICAL完全一致",
    "caption",
    "问题说明",
    "修改建议",
    "是否回放",
    "Type字段",
]


def _suggest(row, types_en, types_zh):
    subtype = row.get("causal_chain_subtype", "")
    cap = row.get("caption", "")
    issues: list[str] = []
    fixes: list[str] = []

    if subtype == "门框后二次进攻链" and types_en == ["shot", "goal"]:
        issues.append("进球却标门框后二次进攻")
        fixes.append("改标：折射/变线入网链 或 其他（进球）；补传球/传中等前置事件")
    if subtype == "射中门柱/横梁链":
        if types_en == ["pass", "shot"]:
            if any(k in cap for k in ("破门", "打进", "进球")):
                issues.append("caption为进球却标门柱链")
                fixes.append("改标：折射/变线入网链 或 其他（进球）")
            elif "传中" in cap or "角球" in cap:
                issues.append("caption为传中/角球但事件仅传球→射门，且无门柱语义")
                fixes.append("事件补：角球/传中；按实际结果改子类型")
            else:
                issues.append("标门柱链但无门柱/横梁语义，且事件非射门→射门")
                fixes.append("改标或补第二脚射门；确认是否中柱")
        elif types_en == ["free_kick"]:
            if "界外球" in cap:
                issues.append("caption为界外球但事件为任意球")
                fixes.append("事件改：界外球；改标：手抛球/快发定位球链")
            else:
                issues.append("仅任意球一个事件，与门柱链无关")
                fixes.append("改标：快发定位球链；或取消因果链")
        elif types_en == ["dribble_past", "shot"]:
            issues.append("标门柱链但caption强调过人，无门柱语义")
            fixes.append("按实际射门结果改标；补完整事件")
    if subtype == "门将脱手致险链" and types_en == ["shot", "keeper_save"]:
        issues.append("仅射门→扑救，无脱手后二攻")
        fixes.append("改标：射门扑救链")
    if subtype == "门线极限救险链":
        if types_en == ["shot", "goal_line_clearance"] and any(
            k in cap for k in ("没收", "扑", "封挡")
        ):
            issues.append("caption描述门将扑救/没收，与门线救险事件不一致")
            fixes.append("统一caption与事件：扑救→射门扑救链；门线→保留门线链")
        if types_en == ["pass", "shot", "goal_line_clearance"]:
            issues.append("caption为传球/传中，事件缺传中且前段不匹配")
            fixes.append("补事件：传中；确认是否真是门线救险")
    if subtype == "手抛球发动进攻链" and types_en == ["throw_in", "pass"] and not issues:
        issues.append("事件链不完整（仅界外球→传球）")
        fixes.append("补后续：传中/射门等")
    if subtype == "快发定位球链" and types_en == ["free_kick", "pass"] and not issues:
        issues.append("事件链不完整（仅任意球→传球）")
        fixes.append("补第三事件如射门")
    tid = SUBTYPE_TO_TEMPLATE.get(subtype, "")
    if tid and not consecutive_pairs_allowed(tid, types_en) and not issues:
        issues.append("事件序列不符合该因果链转移规则")
    if tid and not issues and not sequence_matches_template(tid, types_en):
        issues.append("事件序列与典型骨架(CANONICAL)不一致")
    if not issues:
        issues.append("相对合理（建议复核）")
        fixes.append("可保留；建议核对caption与事件一致")
    return "；".join(issues), "；".join(fixes)


def build_rows() -> list[dict[str, str]]:
    causal = [
        r
        for r in json.loads(SRC.read_text(encoding="utf-8"))
        if r.get("is_causal_chain") == "是"
    ]
    rows: list[dict[str, str]] = []
    for i, r in enumerate(causal):
        types_zh = [e.get("type", "") for e in r.get("events", [])]
        types_en = [ZH.get(t, t) for t in types_zh]
        subtype = r.get("causal_chain_subtype", "")
        tid = SUBTYPE_TO_TEMPLATE.get(subtype, "")
        canonical = CANONICAL_SEQUENCES.get(tid, [])
        issue, fix = _suggest(r, types_en, types_zh)
        rows.append(
            {
                "序号": str(i + 1),
                "评测ID": f"oct10_aus_sm_{i:03d}",
                "片段时间段(segment_time_range)": str(r.get("segment_time_range", "")),
                "视频时间(video_time_range)": str(r.get("video_time_range", "")),
                "因果链大类": str(r.get("causal_chain_type", "")),
                "因果链子类型": subtype,
                "系统template_id": tid,
                "典型骨架(CANONICAL)": " | ".join("→".join(s) for s in canonical[:2]),
                "当前事件(中文)": " → ".join(types_zh) if types_zh else "(空)",
                "当前事件(英文)": " → ".join(types_en) if types_en else "(空)",
                "转移规则合法": "是"
                if tid and consecutive_pairs_allowed(tid, types_en)
                else "否",
                "CANONICAL完全一致": "是"
                if tid and sequence_matches_template(tid, types_en)
                else "否",
                "caption": str(r.get("caption", "")),
                "问题说明": issue,
                "修改建议": fix,
                "是否回放": str(r.get("is_replay", "")),
                "Type字段": str(r.get("Type", "")),
            }
        )
    return rows


def write_csv(rows: list[dict[str, str]]) -> None:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
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


def write_xlsx(rows: list[dict[str, str]]) -> None:
    OUT_XLSX.parent.mkdir(parents=True, exist_ok=True)
    summary_headers = ["问题类型", "条数", "涉及评测ID"]
    summary_rows = [
        ["进球误标门框后二次进攻", "9", "008,011-014,022-023,028,030"],
        ["门柱链但无门柱语义/事件不符", "12", "000,002-003,005-010,016,018,020-021,024,026-027,029"],
        ["脱手链但只有扑救", "3", "017,019,025"],
        ["门线链caption与事件不一致", "3", "004,006,007"],
        ["链条不完整(可补事件)", "4", "001,009,015等"],
    ]
    sheet1 = _sheet_xml(rows, COLUMNS)
    sheet2 = _sheet_xml(
        [dict(zip(summary_headers, r)) for r in summary_rows],
        summary_headers,
    )
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
    with zipfile.ZipFile(OUT_XLSX, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet1)
        z.writestr("xl/worksheets/sheet2.xml", sheet2)


def main() -> None:
    rows = build_rows()
    write_csv(rows)
    write_xlsx(rows)
    print(f"wrote {OUT_XLSX}")
    print(f"wrote {OUT_CSV}")
    print(f"rows={len(rows)}")


if __name__ == "__main__":
    main()
