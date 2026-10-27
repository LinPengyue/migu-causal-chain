"""导出 chain4 评测报告（xlsx / csv / jsonl）。"""

from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from causal_chain8.eval.metrics import EvalSummary, RowScore
from causal_chain8.schema.templates import template_label_zh

COLUMNS = [
    "序号",
    "annotation_id",
    "match_id",
    "标注模版(中文)",
    "标注template_id",
    "规则改判template_id",
    "预测template_id",
    "pred与标注一致",
    "pred与改判一致",
    "标注转移合法",
    "预测转移合法",
    "抽取(全→出)",
    "抽取有效",
    "映射警告",
    "片段时间",
    "问题说明",
    "修改建议",
]


def _suggest_fix(row: RowScore) -> tuple[str, str]:
    issues = list(row.issues)
    fixes: list[str] = []
    gold_zh = template_label_zh(row.gold_template_id)
    relabel_zh = template_label_zh(row.gold_relabel)
    pred_zh = template_label_zh(row.pred_template_id)

    if not row.gold_trans_ok:
        fixes.append("按 chain_rules 精简/修正事件序列，使转移合法")
    if row.gold_template_id == "outcome_other" and row.gold_relabel != "outcome_other":
        fixes.append(f"建议改标：{relabel_zh}")
    if row.rule_top1 != row.gold_template_id and row.gold_template_id != "outcome_other":
        fixes.append(f"规则倾向：{relabel_zh}（当前 {gold_zh}）")
    if row.mapping_warnings:
        fixes.append("事件 type 改用34类标准名；传中勿写传球+Cross")

    if not issues:
        issues.append("相对合理（建议复核）")
    if not fixes:
        fixes.append("可保留或人工看视频复核")

    return "；".join(issues), "；".join(dict.fromkeys(fixes))


def _row_to_dict(i: int, row: RowScore) -> dict[str, str]:
    issue, fix = _suggest_fix(row)
    return {
        "序号": str(i),
        "annotation_id": row.annotation_id,
        "match_id": row.match_id,
        "标注模版(中文)": template_label_zh(row.gold_template_id),
        "标注template_id": row.gold_template_id,
        "规则改判template_id": row.gold_relabel,
        "预测template_id": row.pred_template_id,
        "pred与标注一致": "是" if row.correct_vs_gold else "否",
        "pred与改判一致": "是" if row.correct_vs_relabel else "否",
        "标注转移合法": "是" if row.gold_trans_ok else "否",
        "预测转移合法": "是" if row.pred_trans_ok else "否",
        "抽取(全→出)": f"{row.extract_len_full}→{row.extract_len_out}",
        "抽取有效": "是" if row.extract_seq_match else "否",
        "映射警告": "; ".join(row.mapping_warnings),
        "片段时间": str(row.meta.get("segment_time_sketch", "")),
        "问题说明": issue,
        "修改建议": fix,
    }


def write_csv(summary: EvalSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [_row_to_dict(i + 1, r) for i, r in enumerate(summary.rows)]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def _xlsx_sheet(rows: list[list[str]]) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
    out.append(
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    )
    out.append("<sheetData>")
    for r_idx, row in enumerate(rows, 1):
        out.append(f'<row r="{r_idx}">')
        for c_idx, val in enumerate(row, 1):
            col = chr(64 + c_idx) if c_idx <= 26 else "A" + chr(64 + c_idx - 26)
            out.append(
                f'<c r="{col}{r_idx}" t="inlineStr"><is><t>{escape(str(val))}</t></is></c>'
            )
        out.append("</row>")
    out.append("</sheetData></worksheet>")
    return "".join(out)


def write_xlsx(summary: EvalSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = [COLUMNS]
    for i, r in enumerate(summary.rows):
        table.append([_row_to_dict(i + 1, r)[c] for c in COLUMNS])

    sheet = _xlsx_sheet(table)
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    wb_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="chain4_report" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)


def write_predictions_jsonl(
    summary: EvalSummary,
    path: Path,
    *,
    profile_name: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for row in summary.rows:
        lines.append(
            json.dumps(
                {
                    "annotation_id": row.annotation_id,
                    "match_id": row.match_id,
                    "profile": profile_name,
                    "gold_template_id": row.gold_template_id,
                    "gold_relabel_template_id": row.gold_relabel,
                    "pred_template_id": row.pred_template_id,
                    "correct_vs_gold": row.correct_vs_gold,
                    "correct_vs_relabel": row.correct_vs_relabel,
                    "gold_trans_ok": row.gold_trans_ok,
                    "pred_trans_ok": row.pred_trans_ok,
                    "mapping_warnings": row.mapping_warnings,
                    "issues": row.issues,
                    "meta": row.meta,
                },
                ensure_ascii=False,
            )
        )
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
