"""因果链分类（对齐 causal_chain2.test，支持 causal JSON + profile 映射）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch

from causal_chain2.a3_schema import A3Record
from causal_chain2.agent_classify import AgentTrace, classify_record_agent
from causal_chain2.event_io import events_for_output
from causal_chain2.llm_classify import classify_record
from causal_chain2.llm_qwen import load_qwen
from causal_chain2.model import LiteGCN

from causal_chain4.config import load_profile
from causal_chain4.data_load import load_classify_records
from causal_chain4.io.eval_record import EvalRecord
from causal_chain4.llm.agent import AgentV4Trace, classify_record_v4
from causal_chain4.schema.templates import CHAIN4_TEMPLATES

_OTHER_FAMILY = {
    "outcome_other",
    "individual_breakthrough_goal",
    "team_buildup_goal",
    "corner_coop_goal",
}


def _labels_match(true_tid: str, pred_tid: str, *, soft_other: bool) -> bool:
    if true_tid == pred_tid:
        return True
    if soft_other and true_tid == "outcome_other" and pred_tid in _OTHER_FAMILY:
        return True
    if soft_other and pred_tid == "outcome_other" and true_tid in _OTHER_FAMILY:
        return True
    # 角球配合 vs 角球传中：同属角球进球叙事时软一致
    if soft_other and {true_tid, pred_tid} <= {"corner_coop_goal", "corner_cross_goal"}:
        return True
    return False


def _a3_to_eval_record(rec: A3Record) -> EvalRecord:
    return EvalRecord(
        annotation_id=rec.annotation_id,
        match_id=rec.match_id,
        gold_template_id=rec.chain_template_id,
        gold_category=rec.chain_category,
        gold_label_zh=CHAIN4_TEMPLATES.get(rec.chain_template_id, {}).get("label_zh", ""),
        gold_category_zh="",
        events_raw=list(rec.events_raw),
        events_normalized=list(rec.events_normalized),
        events_extracted=list(rec.events_normalized),
        mapping_warnings=list((rec.validation or {}).get("warnings") or []),
        meta=dict(rec.validation or {}),
    )


def _prediction_row(rec: A3Record, *, pred_template: str, pred_category: str, parse_ok: bool = True, **extra) -> dict:
    row = {
        "annotation_id": rec.annotation_id,
        "match_id": rec.match_id,
        "true_chain_template_id": rec.chain_template_id,
        "pred_chain_template_id": pred_template,
        "true_chain_category": rec.chain_category,
        "pred_chain_category": pred_category,
        "correct": pred_template == rec.chain_template_id,
        "parse_ok": parse_ok,
        "events": events_for_output(rec.events_normalized),
        **extra,
    }
    return row


def run_classify(
    rows: List[A3Record],
    *,
    backend: str,
    model_path: Optional[str],
    ckpt: Optional[Path],
    device: str,
    max_new_tokens: int = 512,
    two_stage: bool = True,
    full_llm: bool = False,
    skip_critic_llm: bool = False,
    ambiguous_margin: float = 0.12,
    trace_dir: Optional[Path] = None,
    out_predictions: Optional[Path] = None,
    profile: Optional[Dict[str, Any]] = None,
    soft_other: bool = True,
) -> Dict[str, Any]:
    profile = profile or {"rules_mode": "annotation"}

    if backend == "chain4_agent":
        # 使用 causal_chain4 业务骨架；有 model_path 时开启 hybrid LLM
        if model_path:
            profile = dict(profile)
            profile.setdefault("llm", {})["enabled"] = True
            profile.setdefault("llm", {})["ambiguous_margin"] = ambiguous_margin
            model, processor = load_qwen(model_path, device)
        else:
            model = processor = None
        ok = soft_ok = parse_fail = fast = 0
        pred_lines: List[str] = []
        if trace_dir:
            trace_dir.mkdir(parents=True, exist_ok=True)
        for i, rec in enumerate(rows):
            ev = _a3_to_eval_record(rec)
            tr = AgentV4Trace()
            result = classify_record_v4(
                ev,
                profile=profile,
                model=model,
                processor=processor,
                device=device,
                max_new_tokens=max_new_tokens,
                trace=tr,
            )
            if tr.mode in ("rule_only", "rule_fast"):
                fast += 1
            if not result.parse_ok:
                parse_fail += 1
            exact = result.chain_template_id == rec.chain_template_id
            soft = _labels_match(rec.chain_template_id, result.chain_template_id, soft_other=soft_other)
            if exact:
                ok += 1
            if soft:
                soft_ok += 1
            if out_predictions is not None:
                pred_lines.append(
                    json.dumps(
                        _prediction_row(
                            rec,
                            pred_template=result.chain_template_id,
                            pred_category=result.chain_category,
                            parse_ok=result.parse_ok,
                            backend="chain4_agent",
                            mode=tr.mode,
                            confidence=result.confidence,
                            margin=result.margin,
                            soft_correct=soft,
                        ),
                        ensure_ascii=False,
                    )
                )
            if (i + 1) % 10 == 0 or i + 1 == len(rows):
                print(
                    f"  progress {i + 1}/{len(rows)}  "
                    f"acc={ok / (i + 1):.4f}  soft_acc={soft_ok / (i + 1):.4f}"
                )
        if out_predictions is not None:
            out_predictions.parent.mkdir(parents=True, exist_ok=True)
            out_predictions.write_text("\n".join(pred_lines) + ("\n" if pred_lines else ""), encoding="utf-8")
        n = len(rows)
        return {
            "backend": "chain4_agent",
            "samples": n,
            "accuracy": ok / max(n, 1),
            "soft_accuracy": soft_ok / max(n, 1),
            "parse_fail": parse_fail,
            "fast_path": fast,
        }

    if backend == "agent":
        if not model_path:
            raise SystemExit("--backend agent 需要 --model-path")
        model, processor = load_qwen(model_path, device)
        ok = parse_fail = fast = 0
        pred_lines = []
        if trace_dir:
            trace_dir.mkdir(parents=True, exist_ok=True)
        for i, rec in enumerate(rows):
            tr = AgentTrace()
            result = classify_record_agent(
                model,
                processor,
                rec,
                device=device,
                max_new_tokens=max_new_tokens,
                trace=tr,
                skip_critic_llm=skip_critic_llm,
                full_llm=full_llm,
                ambiguous_margin=ambiguous_margin,
            )
            if tr.fast_path:
                fast += 1
            if not result.parse_ok:
                parse_fail += 1
            if result.chain_template_id == rec.chain_template_id:
                ok += 1
            if out_predictions is not None:
                pred_lines.append(
                    json.dumps(
                        _prediction_row(
                            rec,
                            pred_template=result.chain_template_id,
                            pred_category=result.chain_category,
                            parse_ok=result.parse_ok,
                            backend="agent",
                            mode=tr.mode,
                            fast_path=tr.fast_path,
                            confidence=result.confidence,
                            margin=result.margin,
                        ),
                        ensure_ascii=False,
                    )
                )
            if (i + 1) % 10 == 0 or i + 1 == len(rows):
                print(f"  progress {i + 1}/{len(rows)}  running_acc={ok / (i + 1):.4f}")
        if out_predictions is not None:
            out_predictions.parent.mkdir(parents=True, exist_ok=True)
            out_predictions.write_text("\n".join(pred_lines) + ("\n" if pred_lines else ""), encoding="utf-8")
        n = len(rows)
        return {
            "backend": "agent",
            "samples": n,
            "accuracy": ok / max(n, 1),
            "parse_fail": parse_fail,
            "fast_path": fast,
        }

    if backend == "llm":
        if not model_path:
            raise SystemExit("--backend llm 需要 --model-path")
        model, processor = load_qwen(model_path, device)
        ok = parse_fail = 0
        pred_lines = []
        for i, rec in enumerate(rows):
            result = classify_record(
                model,
                processor,
                rec,
                device=device,
                max_new_tokens=max_new_tokens,
                two_stage=two_stage,
            )
            if not result.parse_ok:
                parse_fail += 1
            if result.chain_template_id == rec.chain_template_id:
                ok += 1
            if out_predictions is not None:
                pred_lines.append(
                    json.dumps(
                        _prediction_row(
                            rec,
                            pred_template=result.chain_template_id,
                            pred_category=result.chain_category,
                            parse_ok=result.parse_ok,
                            backend="llm",
                            confidence=result.confidence,
                            margin=result.margin,
                        ),
                        ensure_ascii=False,
                    )
                )
        if out_predictions is not None:
            out_predictions.parent.mkdir(parents=True, exist_ok=True)
            out_predictions.write_text("\n".join(pred_lines) + ("\n" if pred_lines else ""), encoding="utf-8")
        n = len(rows)
        return {"backend": "llm", "samples": n, "accuracy": ok / max(n, 1), "parse_fail": parse_fail}

    if backend == "gnn":
        if not ckpt or not ckpt.is_file():
            raise SystemExit("--backend gnn 需要有效 --ckpt")
        from causal_chain2.dataset import record_to_pack
        from causal_chain2.graph_pack import TEMPLATE_TO_IX

        dev = torch.device(device)
        ck = torch.load(ckpt, map_location=dev, weights_only=False)
        model = LiteGCN(int(ck["in_dim"]), int(ck["hidden"]), int(ck["num_classes"])).to(dev)
        model.load_state_dict(ck["model"])
        model.eval()
        ix_to_template = {v: k for k, v in TEMPLATE_TO_IX.items()}
        ok = 0
        pred_lines = []
        with torch.no_grad():
            for rec in rows:
                pack = record_to_pack(rec, dev)
                logits, _ = model(pack.x, pack.edge_index)
                pred_ix = int(logits.argmax(-1).item())
                pred_tid = ix_to_template[pred_ix]
                if pred_ix == int(pack.y.item()):
                    ok += 1
                if out_predictions is not None:
                    from causal_chain2.chain_schema import CHAIN_TEMPLATES

                    meta = CHAIN_TEMPLATES.get(pred_tid, {})
                    pred_lines.append(
                        json.dumps(
                            _prediction_row(
                                rec,
                                pred_template=pred_tid,
                                pred_category=meta.get("category", ""),
                                backend="gnn",
                            ),
                            ensure_ascii=False,
                        )
                    )
        if out_predictions is not None:
            out_predictions.parent.mkdir(parents=True, exist_ok=True)
            out_predictions.write_text("\n".join(pred_lines) + ("\n" if pred_lines else ""), encoding="utf-8")
        n = len(rows)
        return {"backend": "gnn", "samples": n, "accuracy": ok / max(n, 1)}

    raise SystemExit(f"unknown backend: {backend}")


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="causal_chain4 因果链分类（对齐 causal_chain2.test）")
    ap.add_argument(
        "--data",
        type=Path,
        required=True,
        help="A3 jsonl 或 causal JSON（数组 / causal_chains 包装）",
    )
    ap.add_argument(
        "--profile",
        type=str,
        default="production",
        help="映射配置（causal JSON 时生效）；jsonl 仅用于元数据",
    )
    ap.add_argument(
        "--backend",
        choices=["chain4_agent", "agent", "llm", "gnn"],
        default=None,
        help="默认 chain4_agent（业务骨架）；agent=复用 chain2 hybrid 对照",
    )
    ap.add_argument("--model-path", type=str, default=None)
    ap.add_argument("--ckpt", type=Path, default=None)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--max-new-tokens", type=int, default=512)
    ap.add_argument("--filter-tier", type=str, default=None)
    ap.add_argument(
        "--eval-filter",
        choices=["none", "strict", "unique_seq", "clean"],
        default=None,
        help="默认：jsonl=clean，causal JSON=none",
    )
    ap.add_argument("--single-stage", action="store_true")
    ap.add_argument("--agent-full-llm", action="store_true")
    ap.add_argument("--agent-margin", type=float, default=None)
    ap.add_argument("--skip-critic-llm", action="store_true")
    ap.add_argument("--agent-trace-dir", type=Path, default=None)
    ap.add_argument("--out-predictions", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=0)
    return ap


def main(argv: list[str] | None = None) -> None:
    ap = build_argparser()
    args = ap.parse_args(argv)

    profile = load_profile(args.profile)
    cls_cfg = profile.get("classify") or {}

    data_path = args.data.expanduser().resolve()
    eval_filter = args.eval_filter
    if eval_filter is None:
        eval_filter = str(cls_cfg.get("eval_filter", "none" if data_path.suffix.lower() == ".json" else "clean"))

    rows = load_classify_records(
        data_path,
        profile=profile,
        filter_tier=args.filter_tier,
        eval_filter=eval_filter,
    )
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]
    if not rows:
        raise SystemExit("empty dataset after filter/limit")
    print(f"profile={profile.get('name')}  eval_filter={eval_filter}  samples={len(rows)}")

    if args.backend is not None:
        backend = args.backend
    elif args.ckpt is not None and not args.model_path:
        backend = "gnn"
    else:
        backend = str(cls_cfg.get("backend", "chain4_agent"))

    margin = args.agent_margin
    if margin is None:
        margin = float(cls_cfg.get("agent_margin", 0.12))
    soft_other = bool(cls_cfg.get("soft_other", True))

    stats = run_classify(
        rows,
        backend=backend,
        model_path=args.model_path,
        ckpt=args.ckpt.expanduser().resolve() if args.ckpt else None,
        device=args.device,
        max_new_tokens=args.max_new_tokens,
        two_stage=not args.single_stage,
        full_llm=args.agent_full_llm,
        skip_critic_llm=args.skip_critic_llm,
        ambiguous_margin=margin,
        trace_dir=args.agent_trace_dir,
        out_predictions=args.out_predictions,
        profile=profile,
        soft_other=soft_other,
    )
    msg = (
        f"backend={stats['backend']}  samples={stats['samples']}  "
        f"accuracy={stats['accuracy']:.4f}"
    )
    if "soft_accuracy" in stats:
        msg += f"  soft_accuracy={stats['soft_accuracy']:.4f}"
    if "parse_fail" in stats:
        msg += f"  parse_fail={stats['parse_fail']}"
    if "fast_path" in stats:
        msg += f"  fast_path={stats['fast_path']}/{stats['samples']}"
    print(msg)
    if args.out_predictions:
        print(f"wrote predictions -> {args.out_predictions}")


if __name__ == "__main__":
    main()
