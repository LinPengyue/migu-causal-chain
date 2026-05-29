"""加载 checkpoint 在 A3 jsonl 上评估准确率。"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch

from causal_chain2.dataset import filter_by_tier, load_a3_jsonl, record_to_pack
from causal_chain2.model import LiteGCN


def main() -> None:
    ap = argparse.ArgumentParser(description="causal_chain2 GNN 测试")
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--ckpt", type=Path, required=True)
    ap.add_argument("--device", default="cpu")
    ap.add_argument(
        "--filter-tier",
        type=str,
        default=None,
        help="与 train 相同；用于对齐训练分布",
    )
    args = ap.parse_args()

    data_path = args.data.expanduser().resolve()
    ckpt_path = args.ckpt.expanduser().resolve()
    if not data_path.is_file():
        raise SystemExit(
            f"找不到评估数据文件: {data_path}\n"
            "请先生成 eval，例如: python -m causal_chain2.generate --format a3 --mode random_walk "
            "-n 50 -o out/eval_a3.jsonl --seed 99\n"
            "或改用已有 jsonl 的绝对路径，例如训练集: .../out/train_a3.jsonl"
        )
    if not ckpt_path.is_file():
        raise SystemExit(f"找不到 checkpoint: {ckpt_path}")

    dev = torch.device(args.device)
    ck = torch.load(ckpt_path, map_location=dev, weights_only=False)
    model = LiteGCN(
        int(ck["in_dim"]),
        int(ck["hidden"]),
        int(ck["num_classes"]),
    ).to(dev)
    model.load_state_dict(ck["model"])
    model.eval()

    rows = filter_by_tier(load_a3_jsonl(data_path), args.filter_tier)
    ok = 0
    with torch.no_grad():
        for rec in rows:
            pack = record_to_pack(rec, dev)
            logits, _ = model(pack.x, pack.edge_index)
            if int(logits.argmax(-1).item()) == int(pack.y.item()):
                ok += 1
    acc = ok / max(len(rows), 1)
    print(f"samples={len(rows)}  accuracy={acc:.4f}")


if __name__ == "__main__":
    main()
