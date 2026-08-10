"""CLI 公共：profile / 模型加载。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Tuple

from causal_chain4.config import load_profile


def add_common_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--input", type=Path, required=True, help="causal JSON 输入")
    ap.add_argument(
        "--profile",
        type=str,
        default="production",
        help="config 名称或 JSON 路径",
    )
    ap.add_argument("--model-path", type=str, default=None)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--video-root", type=str, default=None)
    ap.add_argument("--enable-llm", action="store_true")
    ap.add_argument("--enable-vlm", action="store_true")
    ap.add_argument("--limit", type=int, default=0)


def resolve_profile_and_model(args) -> Tuple[dict, Any, Any]:
    profile = load_profile(args.profile)
    if args.enable_llm:
        profile.setdefault("llm", {})["enabled"] = True
    if args.enable_vlm:
        profile.setdefault("vlm", {})["enabled"] = True

    model = processor = None
    llm_on = bool((profile.get("llm") or {}).get("enabled"))
    vlm_on = bool((profile.get("vlm") or {}).get("enabled"))
    extract_llm = bool((profile.get("extract") or {}).get("llm_refine"))
    if (llm_on or vlm_on or extract_llm) and args.model_path:
        from causal_chain2.llm_qwen import load_qwen

        model, processor = load_qwen(args.model_path, args.device)
    return profile, model, processor
