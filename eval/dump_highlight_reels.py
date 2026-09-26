#!/usr/bin/env python3
"""独立导出：每场比赛完整集锦 reel（不改现有评测脚本）。

复用 eval_common.build_highlight_clips（与 offline highlight 同源：
select_moments → classify/refine → assemble_reel）。

默认 rule-only；可选 --use-llm。

用法（在 8.31causal_chain 根目录）：

  export PYTHONPATH="$PWD/algo:$PWD/eval"
  python eval/dump_highlight_reels.py
  python eval/dump_highlight_reels.py --out-dir reports/reels_dump --limit-matches 2
  python eval/dump_highlight_reels.py --use-llm --model-path /path/to/Qwen2.5-VL

输出：
  <out-dir>/<safe_id>.json          # 每场完整 reel
  <out-dir>/_manifest.json          # 场次清单与统计
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "algo"))
sys.path.insert(0, str(ROOT / "eval"))

from causal_chain8.config import load_profile  # noqa: E402
from causal_chain8.highlight_io import write_reel_json  # noqa: E402
from eval_common import (  # noqa: E402
    REPORTS,
    ROOT as _ROOT,
    build_highlight_clips,
    load_highlight_gold,
    load_index,
    load_timeline_events,
    make_match_pbar,
    should_drop_t2_for_gold,
)


def _clip_to_dict(c: Any) -> Dict[str, Any]:
    if hasattr(c, "to_dict"):
        return c.to_dict()
    if isinstance(c, dict):
        return dict(c)
    return {
        "clip_id": str(getattr(c, "clip_id", "")),
        "t0_ms": int(getattr(c, "t0_ms", 0) or 0),
        "t1_ms": int(getattr(c, "t1_ms", 0) or 0),
        "chain_category": str(getattr(c, "chain_category", "") or ""),
        "chain_template_id": str(getattr(c, "chain_template_id", "") or ""),
    }


def _build_payload(
    *,
    match_id: str,
    safe_id: str,
    timeline_path: Path,
    events: List[Dict[str, Any]],
    clips: List[Any],
    stats: Dict[str, Any],
    drop_t2: bool,
    use_llm: bool,
    profile_name: str,
) -> Dict[str, Any]:
    clip_dicts = [_clip_to_dict(c) for c in clips]
    ordering = [
        str(c.get("clip_id") or f"clip{i:02d}") for i, c in enumerate(clip_dicts)
    ]
    total_dur = sum(
        max(int(c.get("t1_ms") or 0) - int(c.get("t0_ms") or 0), 0) for c in clip_dicts
    )
    return {
        "match_id": match_id,
        "safe_id": safe_id,
        "input_file": str(timeline_path),
        "event_count": len(events),
        "reel": {
            "clips": clip_dicts,
            "ordering": ordering,
            "total_duration_ms": total_dur,
        },
        "config": {
            "backend": "dump_highlight_reels",
            "profile": profile_name,
            "drop_t2": drop_t2,
            "use_llm": use_llm,
            "pipeline": "select_moments→classify/refine→assemble_reel",
            "aligned_with": "eval/eval_offline_highlight.py logic track",
        },
        "stats": stats,
    }


def main(argv: List[str] | None = None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="Dump per-match highlight reels (new file only)")
    ap.add_argument("--limit-matches", type=int, default=0, help="0=全部场次")
    ap.add_argument("--profile", default="production")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=REPORTS / "reels_dump",
        help="每场 reel JSON 输出目录",
    )
    ap.add_argument("--drop-t2", action="store_true", default=False, help="强制去掉 T2")
    ap.add_argument(
        "--no-t2-auto",
        action="store_true",
        default=True,
        help="按 highlight_gold_no_t2 自动 drop_t2（默认开）",
    )
    ap.add_argument("--keep-t2", action="store_true", help="关闭自动 drop_t2")
    ap.add_argument("--use-llm", action="store_true", default=False)
    ap.add_argument("--model-path", type=str, default="/data2/lpy1/Qwen2.5-VL")
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args(argv)

    auto_drop = bool(args.no_t2_auto) and not args.keep_t2

    profile = dict(load_profile(args.profile))
    profile.setdefault("llm", {})
    profile["llm"] = dict(profile.get("llm") or {})
    profile["llm"]["enabled"] = bool(args.use_llm)

    model = processor = None
    if args.use_llm:
        from causal_chain2.llm_qwen import load_qwen

        print(f"loading Qwen from {args.model_path} on {args.device} ...", flush=True)
        model, processor = load_qwen(args.model_path, args.device)

    matches = load_index()["matches"]
    if args.limit_matches > 0:
        matches = matches[: args.limit_matches]

    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = _ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: List[Dict[str, Any]] = []
    pbar = make_match_pbar("Dump Highlight Reels", len(matches))
    try:
        for mi, meta in enumerate(matches):
            mdir = _ROOT / meta["dir"]
            safe = str(meta.get("safe_id") or f"m{mi}")
            mid = str(meta.get("match_id") or safe)
            timeline_path = mdir / "timeline.json"
            events = load_timeline_events(mdir)
            hl_gold, src_name = load_highlight_gold(mdir)

            drop_t2 = bool(args.drop_t2)
            if auto_drop and not drop_t2:
                drop_t2 = should_drop_t2_for_gold(src_name, hl_gold)

            if not events:
                manifest.append(
                    {
                        "safe_id": safe,
                        "match_id": mid,
                        "ok": False,
                        "reason": "empty_timeline",
                        "n_clips": 0,
                    }
                )
                pbar.update(1)
                continue

            clips, stats = build_highlight_clips(
                events,
                match_id=safe,
                profile=profile,
                drop_t2=drop_t2,
                model=model,
                processor=processor,
                device=args.device if args.use_llm else "cpu",
            )
            payload = _build_payload(
                match_id=mid,
                safe_id=safe,
                timeline_path=timeline_path,
                events=events,
                clips=clips,
                stats=stats,
                drop_t2=drop_t2,
                use_llm=bool(args.use_llm),
                profile_name=args.profile,
            )
            # 文件名与旧 reports/reels 一致：safe_id 截断 60
            out_path = out_dir / f"{safe[:60]}.json"
            write_reel_json(out_path, payload)
            manifest.append(
                {
                    "safe_id": safe,
                    "match_id": mid,
                    "ok": True,
                    "path": str(out_path.relative_to(_ROOT)),
                    "n_events": len(events),
                    "n_clips": len(clips),
                    "drop_t2": drop_t2,
                    "gold_src": src_name,
                    "n_gold": len(hl_gold),
                    "moments_selected": stats.get("moments_selected"),
                    "total_duration_ms": payload["reel"]["total_duration_ms"],
                }
            )
            pbar.set_postfix_str(f"clips={len(clips)} wrote={out_path.name[:40]}")
            pbar.update(1)
    finally:
        pbar.close()

    summary = {
        "n_matches": len(matches),
        "n_ok": sum(1 for m in manifest if m.get("ok")),
        "n_fail": sum(1 for m in manifest if not m.get("ok")),
        "out_dir": str(out_dir),
        "use_llm": bool(args.use_llm),
        "profile": args.profile,
        "auto_drop_t2": auto_drop,
        "matches": manifest,
    }
    man_path = out_dir / "_manifest.json"
    man_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("n_matches", "n_ok", "n_fail", "out_dir")}, ensure_ascii=False, indent=2))
    print(f"wrote {man_path}", flush=True)
    return summary


if __name__ == "__main__":
    main()
