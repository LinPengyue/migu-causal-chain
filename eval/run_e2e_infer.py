#!/usr/bin/env python3
"""脚本 A：仅有上游事件（无 *_causal.json）→ 端到端输出拆条 + 集锦。

不计算逻辑完整率（无标注）。

输入目录默认 data/交付_out/，读取所有「不带 causal」的 *.json。

用法：
  cd 9.31causal_chain
  export PYTHONPATH="$PWD/algo:$PWD/eval"
  python eval/run_e2e_infer.py --limit-matches 2
  python eval/run_e2e_infer.py --src-dir /path/to/上游事件目录
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

from causal_chain8.config import load_profile as load_c8_profile  # noqa: E402
from causal_chain8.highlight_io import write_reel_json  # noqa: E402
from delivery_io import (  # noqa: E402
    default_src_dir,
    list_plain_jsons,
    load_plain_timeline,
    safe_id_from_stem,
)
from eval_common import (  # noqa: E402
    REPORTS,
    ROOT as _ROOT,
    build_highlight_clips,
    make_match_pbar,
)
from strip_adapter import AlgoStripAdapter  # noqa: E402


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


def main(argv: List[str] | None = None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="E2E infer: plain events → strip + highlight")
    ap.add_argument("--src-dir", type=Path, default=None, help="上游事件目录（无 causal json）")
    ap.add_argument("--out-dir", type=Path, default=REPORTS / "e2e_infer")
    ap.add_argument("--limit-matches", type=int, default=0)
    ap.add_argument("--profile", default="production")
    ap.add_argument("--keep-t2", action="store_true")
    args = ap.parse_args(argv)

    src = args.src_dir or default_src_dir()
    if not src.is_dir():
        raise SystemExit(f"missing src-dir: {src}")

    plains = list_plain_jsons(src)
    if args.limit_matches > 0:
        plains = plains[: args.limit_matches]
    if not plains:
        raise SystemExit(f"no plain (non-causal) json under {src}")

    out_dir = args.out_dir if args.out_dir.is_absolute() else _ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    strip_ad = AlgoStripAdapter(profile_name=args.profile, use_llm=False, use_sliding_recall=True)
    hl_profile = dict(load_c8_profile(args.profile))
    hl_profile.setdefault("llm", {})
    hl_profile["llm"] = dict(hl_profile.get("llm") or {})
    hl_profile["llm"]["enabled"] = False
    drop_t2 = not bool(args.keep_t2)

    manifest: List[Dict[str, Any]] = []
    pbar = make_match_pbar("E2E Infer", len(plains))
    try:
        for plain in plains:
            mid, events = load_plain_timeline(plain)
            safe = safe_id_from_stem(plain.stem)
            mdir = out_dir / safe
            mdir.mkdir(parents=True, exist_ok=True)

            # 中间 timeline（便于排查）
            (mdir / "timeline.json").write_text(
                json.dumps(
                    {
                        "match_id": mid,
                        "events": events,
                        "source_plain": str(plain),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            strip_preds = strip_ad.predict(events, match_id=safe) if events else []
            for i, p in enumerate(strip_preds):
                p["clip_id"] = f"clip{i:02d}"
            strip_payload = {
                "match_id": mid,
                "safe_id": safe,
                "mode": "infer_timeline",
                "n_events": len(events),
                "n_chains": len(strip_preds),
                "chains": strip_preds,
                "config": {
                    "algo": "causal_chain6",
                    "note": "无 causal 标注；仅推理输出，不算完整率",
                },
            }
            (mdir / "strip.json").write_text(
                json.dumps(strip_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            clips, build_stats = (
                build_highlight_clips(
                    events, match_id=safe, profile=hl_profile, drop_t2=drop_t2
                )
                if events
                else ([], {})
            )
            clip_dicts = [_clip_to_dict(c) for c in clips]
            ordering = [str(c.get("clip_id") or f"clip{i:02d}") for i, c in enumerate(clip_dicts)]
            total_dur = sum(
                max(int(c.get("t1_ms") or 0) - int(c.get("t0_ms") or 0), 0) for c in clip_dicts
            )
            hl_payload = {
                "match_id": mid,
                "safe_id": safe,
                "event_count": len(events),
                "reel": {
                    "clips": clip_dicts,
                    "ordering": ordering,
                    "total_duration_ms": total_dur,
                },
                "stats": build_stats,
                "config": {
                    "algo": "causal_chain8",
                    "drop_t2": drop_t2,
                    "note": "无 causal 标注；仅推理输出，不算完整率",
                },
            }
            write_reel_json(mdir / "highlight.json", hl_payload)

            manifest.append(
                {
                    "safe_id": safe,
                    "match_id": mid,
                    "source": str(plain.name),
                    "path": str(mdir.relative_to(_ROOT)),
                    "n_events": len(events),
                    "n_strip": len(strip_preds),
                    "n_highlight": len(clip_dicts),
                    "ok": True,
                }
            )
            pbar.set_postfix_str(f"strip={len(strip_preds)} hl={len(clip_dicts)}")
            pbar.update(1)
    finally:
        pbar.close()

    summary = {
        "task": "e2e_infer",
        "src_dir": str(src),
        "out_dir": str(out_dir),
        "n_matches": len(manifest),
        "has_gold": False,
        "logic_complete_rate": None,
        "note": "仅上游事件 → 拆条/集锦输出；无 *_causal.json 故无完整率",
        "matches": manifest,
    }
    man = out_dir / "_manifest.json"
    man.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("task", "n_matches", "out_dir", "note")}, ensure_ascii=False, indent=2))
    print(f"wrote {man}", flush=True)
    return summary


if __name__ == "__main__":
    main()
