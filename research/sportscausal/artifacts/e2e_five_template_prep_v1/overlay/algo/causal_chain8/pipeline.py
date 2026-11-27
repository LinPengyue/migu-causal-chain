"""extract → classify 主流程。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from causal_chain8.extract.core import extract_causal_events
from causal_chain8.io.eval_record import ClassifyResultV4, EvalRecord, PipelineResult
from causal_chain8.io.load_causal_min import load_causal_file
from causal_chain8.llm.agent import AgentV4Trace, classify_record_v4
from causal_chain8.mapping.strategies import apply_mapping_chain
from causal_chain8.rules.rank import rule_top1
from causal_chain8.schema.templates import CHAIN4_TEMPLATES


def classify_extracted_events(
    events: List[Dict[str, Any]],
    *,
    profile: Dict[str, Any],
    rec_meta: Optional[EvalRecord] = None,
    model=None,
    processor=None,
    device: str = "cuda",
    video_root: Optional[str] = None,
) -> ClassifyResultV4:
    llm_on = bool((profile.get("llm") or {}).get("enabled"))
    vlm_on = bool((profile.get("vlm") or {}).get("enabled"))

    if (llm_on or vlm_on) and model is not None and processor is not None and rec_meta is not None:
        # 临时把 extracted 写入 rec 供 agent 使用
        rec_meta.events_extracted = events
        trace = AgentV4Trace()
        result = classify_record_v4(
            rec_meta,
            profile=profile,
            model=model,
            processor=processor,
            device=device,
            video_root=video_root,
            trace=trace,
        )
        return ClassifyResultV4(
            chain_template_id=result.chain_template_id,
            chain_category=result.chain_category,
            confidence=result.confidence,
            rationale=result.rationale,
            mode=trace.mode,
        )

    types = [str(e.get("type", "")) for e in events]
    tid = rule_top1(types, profile=profile)
    ranked_score = 0.85
    return ClassifyResultV4(
        chain_template_id=tid,
        chain_category=CHAIN4_TEMPLATES.get(tid, {}).get("category", "outcome"),
        confidence=ranked_score,
        rationale="rule_top1",
        mode="rule_only",
    )


def run_pipeline_on_row(
    row: Dict[str, Any],
    *,
    profile: Dict[str, Any],
    index: int,
    file_meta: Dict[str, Any],
    source_file: str,
    model=None,
    processor=None,
    device: str = "cuda",
    video_root: Optional[str] = None,
    template_hint: Optional[str] = None,
) -> PipelineResult:
    if file_meta.get("video_name") and "_file_meta" not in row:
        row["_file_meta"] = file_meta
    pack, warnings = apply_mapping_chain(
        row,
        mapping_spec=str(profile.get("mapping", "annotation_compat")),
        index=index,
    )
    meta = dict(pack["meta"])
    meta.setdefault("video_name", file_meta.get("video_name", ""))
    meta.setdefault("source_file", source_file)

    hint = template_hint or pack.get("gold_template_id")
    extract_cfg = profile.get("extract") or {}
    do_extract = extract_cfg.get("enabled", True)

    prefix = pack["annotation_id"].replace("/", "_")[:32]
    if do_extract:
        extraction = extract_causal_events(
            pack["events_normalized"],
            profile=profile,
            template_hint=hint if extract_cfg.get("use_gold_hint") else None,
            prefix=prefix + "_x",
            model=model if extract_cfg.get("llm_refine") else None,
            processor=processor,
            device=device,
        )
        events_for_cls = extraction.events_extracted
    else:
        from causal_chain8.io.extraction_result import ExtractionResult

        extraction = ExtractionResult(
            events_extracted=list(pack["events_normalized"]),
            extracted_indices=list(range(len(pack["events_normalized"]))),
            method="disabled",
            score=1.0,
        )
        events_for_cls = pack["events_normalized"]

    eval_stub = EvalRecord(
        annotation_id=pack["annotation_id"],
        match_id=pack["match_id"],
        gold_template_id=pack["gold_template_id"],
        gold_category=pack["gold_category"],
        gold_label_zh=pack["gold_label_zh"],
        gold_category_zh=pack["gold_category_zh"],
        events_raw=pack["events_raw"],
        events_normalized=pack["events_normalized"],
        events_extracted=events_for_cls,
        extraction=extraction,
        mapping_warnings=warnings,
        meta=meta,
    )

    classification = classify_extracted_events(
        events_for_cls,
        profile=profile,
        rec_meta=eval_stub,
        model=model,
        processor=processor,
        device=device,
        video_root=video_root,
    )

    return PipelineResult(
        annotation_id=pack["annotation_id"],
        match_id=pack["match_id"],
        events_full=pack["events_normalized"],
        extraction=extraction,
        classification=classification,
        gold_template_id=pack["gold_template_id"],
        gold_category=pack["gold_category"],
        gold_label_zh=pack["gold_label_zh"],
        mapping_warnings=warnings,
        meta=meta,
    )


def run_pipeline_file(
    input_path: Path,
    *,
    profile: Dict[str, Any],
    model=None,
    processor=None,
    device: str = "cuda",
    video_root: Optional[str] = None,
    limit: int = 0,
) -> List[PipelineResult]:
    rows, file_meta = load_causal_file(input_path)
    out: List[PipelineResult] = []
    for i, row in enumerate(rows):
        out.append(
            run_pipeline_on_row(
                row,
                profile=profile,
                index=i,
                file_meta=file_meta,
                source_file=input_path.name,
                model=model,
                processor=processor,
                device=device,
                video_root=video_root,
            )
        )
    if limit and limit > 0:
        return out[:limit]
    return out


def pipeline_to_eval_records(
    results: List[PipelineResult],
    *,
    profile: Dict[str, Any],
) -> List[EvalRecord]:
    records: List[EvalRecord] = []
    for r in results:
        rec = EvalRecord(
            annotation_id=r.annotation_id,
            match_id=r.match_id,
            gold_template_id=r.gold_template_id or "",
            gold_category=r.gold_category or "",
            gold_label_zh=r.gold_label_zh,
            gold_category_zh="",
            events_raw=r.events_full,
            events_normalized=r.events_full,
            events_extracted=r.events_extracted,
            extraction=r.extraction,
            mapping_warnings=r.mapping_warnings,
            meta=r.meta,
            pred_template_id=r.classification.chain_template_id,
        )
        rec.gold_template_id_relabel = rule_top1(rec.types_extracted, profile=profile)
        records.append(rec)
    return records
