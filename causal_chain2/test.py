"""在 A3 jsonl 上评估因果链分类（默认 agent 方案 C，可选 llm / gnn）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from causal_chain2.dataset import (
    filter_by_eval_mode,
    filter_by_tier,
    load_a3_jsonl,
    record_to_pack,
)
from causal_chain2.agent_classify import AgentTrace, classify_record_agent
from causal_chain2.llm_classify import classify_record
from causal_chain2.llm_qwen import load_qwen
from causal_chain2.model import LiteGCN


def _eval_gnn(rows, ckpt_path: Path, device: torch.device) -> tuple[int, int]:
    ck = torch.load(ckpt_path, map_location=device, weights_only=False)
    model = LiteGCN(
        int(ck["in_dim"]),
        int(ck["hidden"]),
        int(ck["num_classes"]),
    ).to(device)
    model.load_state_dict(ck["model"])
    model.eval()
    ok = 0
    with torch.no_grad():
        for rec in rows:
            pack = record_to_pack(rec, device)
            logits, _ = model(pack.x, pack.edge_index)
            if int(logits.argmax(-1).item()) == int(pack.y.item()):
                ok += 1
    return ok, len(rows)


def _eval_llm(
    rows,
    *,
    model_path: str,
    device: str,
    max_new_tokens: int,
    two_stage: bool,
) -> tuple[int, int, int]:
    model, processor = load_qwen(model_path, device)
    ok = 0
    parse_fail = 0
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
        if (i + 1) % 20 == 0 or i + 1 == len(rows):
            print(f"  progress {i + 1}/{len(rows)}  running_acc={ok / (i + 1):.4f}")
    return ok, len(rows), parse_fail


def _eval_agent(
    rows,
    *,
    model_path: str,
    device: str,
    max_new_tokens: int,
    skip_critic_llm: bool = False,
    full_llm: bool = False,
    ambiguous_margin: float = 0.12,
    trace_dir: Path | None = None,
) -> tuple[int, int, int, int]:
    model, processor = load_qwen(model_path, device)
    ok = 0
    parse_fail = 0
    fast = 0
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
        if trace_dir:
            trace_path = trace_dir / f"{i:04d}_{rec.annotation_id[:24]}.json"
            trace_path.write_text(
                json.dumps(
                    {
                        "annotation_id": rec.annotation_id,
                        "true_template": rec.chain_template_id,
                        "pred_template": result.chain_template_id,
                        "true_category": rec.chain_category,
                        "pred_category": result.chain_category,
                        "correct": result.chain_template_id == rec.chain_template_id,
                        "rationale": result.rationale,
                        "mode": tr.mode,
                        "fast_path": tr.fast_path,
                        "global_ranked": tr.global_ranked,
                        "planner": tr.planner_rationale,
                        "classifier_candidates": tr.classifier_candidates,
                        "critic_ranked": tr.critic_ranked,
                        "rule_ranked": tr.rule_ranked,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        if (i + 1) % 10 == 0 or i + 1 == len(rows):
            print(f"  progress {i + 1}/{len(rows)}  running_acc={ok / (i + 1):.4f}")
    return ok, len(rows), parse_fail, fast


def main() -> None:
    ap = argparse.ArgumentParser(description="causal_chain2 因果链分类评估")
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument(
        "--backend",
        choices=["agent", "llm", "gnn"],
        default=None,
        help="agent=方案C；llm=两阶段；gnn=LiteGCN；省略时按 --model-path/--ckpt 自动选择",
    )
    ap.add_argument(
        "--model-path",
        type=str,
        default=None,
        help="--backend llm/agent 时 Qwen2.5-VL 权重目录",
    )
    ap.add_argument(
        "--ckpt",
        type=Path,
        default=None,
        help="LiteGCN checkpoint；未指定 --backend 且未给 --model-path 时自动走 gnn",
    )
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--max-new-tokens", type=int, default=512)
    ap.add_argument(
        "--filter-tier",
        type=str,
        default=None,
        help="按 validation.tier 过滤（如 strict,relaxed）",
    )
    ap.add_argument(
        "--eval-filter",
        choices=["none", "strict", "unique_seq", "clean"],
        default="clean",
        help="评测集清洗：clean=strict 或 序列唯一决定模板（默认）",
    )
    ap.add_argument(
        "--single-stage",
        action="store_true",
        help="使用单阶段 18 类（默认两阶段：先 category 再 template）",
    )
    ap.add_argument(
        "--agent-full-llm",
        action="store_true",
        help="agent 使用旧版 5 步全 LLM（易偏低，仅对照）",
    )
    ap.add_argument(
        "--agent-margin",
        type=float,
        default=0.12,
        help="hybrid 模式：规则 top1-top2 分差≥此值则跳过 LLM",
    )
    ap.add_argument(
        "--skip-critic-llm",
        action="store_true",
        help="与 --agent-full-llm 联用：Critic 用规则",
    )
    ap.add_argument(
        "--agent-trace-dir",
        type=Path,
        default=None,
        help="agent 评估：每条样本写出审计 JSON",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="仅评估前 N 条（0 表示全量）",
    )
    args = ap.parse_args()

    data_path = args.data.expanduser().resolve()
    if not data_path.is_file():
        raise SystemExit(f"找不到评估数据文件: {data_path}")

    rows = filter_by_tier(load_a3_jsonl(data_path), args.filter_tier)
    rows = filter_by_eval_mode(rows, args.eval_filter)
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]
    if not rows:
        raise SystemExit("empty dataset after filter/limit")
    print(f"eval_filter={args.eval_filter}  samples={len(rows)}")

    if args.backend is not None:
        backend = args.backend
    elif args.ckpt is not None and not args.model_path:
        backend = "gnn"
    elif args.model_path:
        backend = "agent"
    else:
        backend = "agent"

    if backend == "agent":
        if not args.model_path:
            raise SystemExit("--backend agent 需要 --model-path")
        ok, n, parse_fail, fast_n = _eval_agent(
            rows,
            model_path=args.model_path,
            device=args.device,
            max_new_tokens=args.max_new_tokens,
            skip_critic_llm=args.skip_critic_llm,
            full_llm=args.agent_full_llm,
            ambiguous_margin=args.agent_margin,
            trace_dir=args.agent_trace_dir,
        )
        acc = ok / max(n, 1)
        mode = "full_llm" if args.agent_full_llm else "hybrid"
        print(
            f"backend=agent  mode={mode}  samples={n}  accuracy={acc:.4f}  "
            f"parse_fail={parse_fail}  fast_path={fast_n}/{n}"
        )
        return

    if backend == "llm":
        if not args.model_path:
            raise SystemExit("--backend llm 需要 --model-path（Qwen2.5-VL 目录）")
        ok, n, parse_fail = _eval_llm(
            rows,
            model_path=args.model_path,
            device=args.device,
            max_new_tokens=args.max_new_tokens,
            two_stage=not args.single_stage,
        )
        acc = ok / max(n, 1)
        stage = "two_stage" if not args.single_stage else "single_stage"
        print(
            f"backend=llm  mode={stage}  samples={n}  accuracy={acc:.4f}  "
            f"parse_fail={parse_fail}"
        )
        return

    if backend != "gnn":
        raise SystemExit(f"unknown backend: {backend}")

    if not args.ckpt:
        raise SystemExit("--backend gnn 需要 --ckpt")
    ckpt_path = args.ckpt.expanduser().resolve()
    if not ckpt_path.is_file():
        raise SystemExit(f"找不到 checkpoint: {ckpt_path}")
    dev = torch.device(args.device)
    ok, n = _eval_gnn(rows, ckpt_path, dev)
    acc = ok / max(n, 1)
    print(f"backend=gnn  eval_filter={args.eval_filter}  samples={n}  accuracy={acc:.4f}")


if __name__ == "__main__":
    main()
