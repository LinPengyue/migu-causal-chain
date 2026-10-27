"""多维度评测指标（含抽取）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from causal_chain8.io.eval_record import EvalRecord
from causal_chain8.rules.rank import global_rule_shortlist
from causal_chain8.schema.rules import RulesContext


@dataclass
class RowScore:
    annotation_id: str
    match_id: str
    gold_template_id: str
    gold_relabel: str
    pred_template_id: str
    rule_top1: str
    gold_trans_ok: bool
    pred_trans_ok: bool
    gold_exact: bool
    correct_vs_gold: bool
    correct_vs_relabel: bool
    rule_matches_gold: bool
    extract_seq_match: bool
    extract_len_full: int
    extract_len_out: int
    mapping_warnings: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalSummary:
    n: int = 0
    acc_vs_gold: float = 0.0
    acc_vs_relabel: float = 0.0
    rule_top1_vs_gold: float = 0.0
    gold_transition_valid_rate: float = 0.0
    pred_transition_valid_rate: float = 0.0
    mapping_issue_rate: float = 0.0
    extract_seq_match_rate: float = 0.0
    rows: List[RowScore] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n": self.n,
            "acc_vs_gold": self.acc_vs_gold,
            "acc_vs_relabel": self.acc_vs_relabel,
            "rule_top1_vs_gold": self.rule_top1_vs_gold,
            "gold_transition_valid_rate": self.gold_transition_valid_rate,
            "pred_transition_valid_rate": self.pred_transition_valid_rate,
            "mapping_issue_rate": self.mapping_issue_rate,
            "extract_seq_match_rate": self.extract_seq_match_rate,
        }


def _types_match(a: List[str], b: List[str]) -> bool:
    return a == b


def _issues_for_row(rec: EvalRecord, ctx: RulesContext) -> List[str]:
    issues: List[str] = []
    types = rec.types_extracted
    gold = rec.gold_template_id

    check = ctx.check_transitions(gold, types)
    if not check["allowed"]:
        issues.append("gold转移不合法")
    if not check["exact_canonical_match"]:
        issues.append("gold与CANONICAL不一致")

    relabel = rec.gold_template_id_relabel or ""
    if gold == "outcome_other" and relabel and relabel != "outcome_other":
        issues.append(f"标「其他」但规则倾向{relabel}")

    if rec.mapping_warnings:
        issues.append("映射警告:" + ";".join(rec.mapping_warnings[:3]))

    if rec.extraction and rec.extraction.method == "fallback_full":
        issues.append("抽取未命中CANONICAL，保留全序列")

    return issues


def score_records(
    records: List[EvalRecord],
    *,
    profile: Dict[str, Any],
    predictions: Optional[Dict[str, str]] = None,
) -> EvalSummary:
    ctx = RulesContext.from_profile(profile)
    rows: List[RowScore] = []
    predictions = predictions or {}

    for rec in records:
        types = rec.types_extracted
        rule_top = rec.gold_template_id_relabel or global_rule_shortlist(types, profile=profile, top_k=1)[0]["chain_template_id"]
        pred = predictions.get(rec.annotation_id) or rec.pred_template_id or rule_top

        gold_check = ctx.check_transitions(rec.gold_template_id, types)
        pred_check = ctx.check_transitions(pred, types)

        extract_match = _types_match(rec.types_extracted, rec.types_normalized) is False and (
            len(rec.events_extracted) < len(rec.events_normalized)
        )
        # 序列级：抽取后 type 链是否为全链的子序列且更短
        full = rec.types_normalized
        ext = rec.types_extracted
        if ext and full and ext != full:
            j = 0
            matched = True
            for t in ext:
                while j < len(full) and full[j] != t:
                    j += 1
                if j >= len(full):
                    matched = False
                    break
                j += 1
            extract_match = matched and len(ext) <= len(full)

        row = RowScore(
            annotation_id=rec.annotation_id,
            match_id=rec.match_id,
            gold_template_id=rec.gold_template_id,
            gold_relabel=rule_top,
            pred_template_id=pred,
            rule_top1=rule_top,
            gold_trans_ok=gold_check["allowed"],
            pred_trans_ok=pred_check["allowed"],
            gold_exact=gold_check["exact_canonical_match"],
            correct_vs_gold=pred == rec.gold_template_id,
            correct_vs_relabel=pred == rule_top,
            rule_matches_gold=rule_top == rec.gold_template_id,
            extract_seq_match=extract_match,
            extract_len_full=len(rec.events_normalized),
            extract_len_out=len(rec.events_extracted),
            mapping_warnings=list(rec.mapping_warnings),
            issues=_issues_for_row(rec, ctx),
            meta=dict(rec.meta),
        )
        rows.append(row)

    n = max(len(rows), 1)
    summary = EvalSummary(
        n=len(rows),
        acc_vs_gold=sum(r.correct_vs_gold for r in rows) / n,
        acc_vs_relabel=sum(r.correct_vs_relabel for r in rows) / n,
        rule_top1_vs_gold=sum(r.rule_matches_gold for r in rows) / n,
        gold_transition_valid_rate=sum(r.gold_trans_ok for r in rows) / n,
        pred_transition_valid_rate=sum(r.pred_trans_ok for r in rows) / n,
        mapping_issue_rate=sum(1 for r in rows if r.mapping_warnings) / n,
        extract_seq_match_rate=sum(r.extract_seq_match for r in rows) / n,
        rows=rows,
    )
    return summary
