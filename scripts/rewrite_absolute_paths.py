#!/usr/bin/env python3
"""将包内绝对路径改写为相对包根路径（打包部署用）。一次性脚本。"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 长前缀优先
REPLACEMENTS = [
    (str(ROOT) + "/", ""),
    ("/data2/lpy1/causal-chain2/8.31causal_chain/", ""),
    ("/data2/lpy1/causal-chain2/10.31causal_chain/", ""),
    (
        "/data2/lpy1/causal-chain2/causal_chain/examples/交付_out/",
        "data/交付_out/",
    ),
    ("/data2/lpy1/Qwen2.5-VL", "./models/Qwen2.5-VL"),
    ("/home/lpy1/.conda/envs/mllms_know/bin/python", "conda run -n mllms_know python"),
]

SKIP_DIRS = {"data"}  # 原始交付数据不改时间戳数字；但 data 下若有绝对路径说明也可改？
# 只改 text 类；跳过巨大无关二进制。data/交付_out 里的 event_time 10.31 不应被误伤——我们的替换不含裸 10.31


def should_touch(p: Path) -> bool:
    if p.suffix not in {".json", ".md", ".py", ".txt", ".jsonl", ".sh"}:
        return False
    # 跳过本脚本，避免替换表被自身改写清空
    if p.name == "rewrite_absolute_paths.py":
        return False
    # 跳过交付原始大 JSON（只含时间戳偶然命中）
    if "交付_out" in p.parts and p.parent.name == "交付_out":
        return False
    return True


def rewrite(text: str) -> str:
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text


def main() -> None:
    n_files = 0
    for p in ROOT.rglob("*"):
        if not p.is_file() or not should_touch(p):
            continue
        try:
            raw = p.read_text(encoding="utf-8")
        except Exception:
            continue
        new = rewrite(raw)
        if new != raw:
            p.write_text(new, encoding="utf-8")
            n_files += 1
            print(p.relative_to(ROOT))
    print(f"updated_files={n_files}")


if __name__ == "__main__":
    main()
