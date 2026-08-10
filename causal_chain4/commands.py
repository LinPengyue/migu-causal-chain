"""causal_chain4 子命令注册。"""

from __future__ import annotations

import argparse
from pathlib import Path


def register_classify(sub) -> None:
    ap = sub.add_parser(
        "classify",
        help="因果链分类（对齐 causal_chain2.test；--data 支持 jsonl / causal JSON）",
    )
    ap.add_argument("extra", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    ap.set_defaults(func=_run_classify)


def register_strip(sub) -> None:
    ap = sub.add_parser(
        "strip",
        help="时间线拆条（对齐 causal_chain2.timeline_highlights）",
    )
    ap.add_argument("extra", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    ap.set_defaults(func=_run_strip)


def register_pipeline(sub) -> None:
    ap = sub.add_parser("pipeline", help="[可选] 抽取+分类实验")
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--profile", type=str, default="oct10_causal2")
    ap.add_argument("--out-jsonl", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.set_defaults(func=_run_pipeline_legacy)


def register_extract(sub) -> None:
    ap = sub.add_parser("extract", help="[可选] CANONICAL 抽取实验")
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--profile", type=str, default="oct10_causal2")
    ap.add_argument("--out-jsonl", type=Path, default=None)
    ap.set_defaults(func=_run_extract_legacy)


def register_eval(sub) -> None:
    ap = sub.add_parser("eval", help="[可选] 标注对比评测")
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--profile", type=str, default="oct10_causal2")
    ap.add_argument("--model-path", type=str, default=None)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--report-xlsx", type=Path, default=None)
    ap.add_argument("--report-csv", type=Path, default=None)
    ap.add_argument("--out-predictions", type=Path, default=None)
    ap.add_argument("--show-transition-debug", action="store_true")
    ap.set_defaults(func=_run_eval_legacy)


def _run_classify(args) -> None:
    from causal_chain4.classify import main as classify_main

    extra = list(args.extra or [])
    if extra and extra[0] == "--":
        extra = extra[1:]
    classify_main(extra if extra else None)


def _run_strip(args) -> None:
    from causal_chain4.strip import main as strip_main

    extra = list(args.extra or [])
    if extra and extra[0] == "--":
        extra = extra[1:]
    strip_main(extra if extra else None)


def _run_pipeline_legacy(args) -> None:
    from causal_chain4.config import load_profile
    from causal_chain4.io.emit_a3 import write_pipeline_jsonl
    from causal_chain4.pipeline import run_pipeline_file

    profile = load_profile(args.profile)
    results = run_pipeline_file(args.input.expanduser().resolve(), profile=profile, limit=args.limit)
    print(f"legacy pipeline samples={len(results)}")
    if args.out_jsonl:
        write_pipeline_jsonl(results, args.out_jsonl.expanduser().resolve())


def _run_extract_legacy(args) -> None:
    import json

    from causal_chain4.config import load_profile
    from causal_chain4.extract.core import extract_causal_events
    from causal_chain4.io.load_causal_min import load_causal_file
    from causal_chain4.mapping.strategies import apply_mapping_chain

    profile = load_profile(args.profile)
    rows, meta = load_causal_file(args.input.expanduser().resolve())
    lines = []
    for i, row in enumerate(rows):
        row.setdefault("_file_meta", meta)
        pack, _ = apply_mapping_chain(row, mapping_spec=str(profile.get("mapping", "annotation_compat")), index=i)
        ext = extract_causal_events(pack["events_normalized"], profile=profile, prefix=pack["annotation_id"][:32])
        lines.append(json.dumps({"annotation_id": pack["annotation_id"], "extraction": ext.to_dict()}, ensure_ascii=False))
        print(f"{pack['annotation_id']}: {len(pack['events_normalized'])} -> {len(ext.events_extracted)}")
    if args.out_jsonl:
        args.out_jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_eval_legacy(args) -> None:
    from causal_chain4.config import load_profile
    from causal_chain4.eval.metrics import score_records
    from causal_chain4.eval.report import write_csv, write_predictions_jsonl, write_xlsx
    from causal_chain4.preprocess.normalize import build_eval_records

    profile = load_profile(args.profile)
    records = build_eval_records(args.input.expanduser().resolve(), profile=profile)
    predictions = {r.annotation_id: r.pred_template_id or "" for r in records}
    summary = score_records(records, profile=profile, predictions=predictions)
    print(f"samples={summary.n}  acc_vs_gold={summary.acc_vs_gold:.4f}")
    if args.show_transition_debug:
        print(f"  gold_transition_valid={summary.gold_transition_valid_rate:.4f}")
    if args.report_xlsx:
        write_xlsx(summary, args.report_xlsx.expanduser().resolve())
    if args.report_csv:
        write_csv(summary, args.report_csv.expanduser().resolve())
    if args.out_predictions:
        write_predictions_jsonl(summary, args.out_predictions.expanduser().resolve(), profile_name=str(profile.get("name")))
