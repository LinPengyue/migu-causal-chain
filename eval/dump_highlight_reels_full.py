#!/usr/bin/env python3
"""交付用集锦导出（完整 PDF 规则 + 片数保底）。

与 eval/dump_highlight_reels.py 的区别：
- 默认 **不 drop T2**（规则四可补片）
- 选片后若仍 < min_clips，从剩余高价值 T1/T2 槽位补到保底（标注为 presentation_fill）
- 默认输出到 reports/reels_dump_full/，不覆盖原 reels_dump（no_t2 评测对齐）

用法：
  export PYTHONPATH="$PWD/algo:$PWD/eval"
  python eval/dump_highlight_reels_full.py
  python eval/dump_highlight_reels_full.py --min-clips 6 --limit-matches 2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "algo"))
sys.path.insert(0, str(ROOT / "eval"))

from causal_chain8.config import load_profile  # noqa: E402
from causal_chain8.highlight_io import write_reel_json  # noqa: E402
from causal_chain8.select_moments import (  # noqa: E402
    HALF_MS_DEFAULT,
    T1_NEAR_DUP_MS,
    collect_t0,
    collect_valuable_t1,
    collect_valuable_t2,
    dedupe_near,
    merge_overlapping,
    pick_per_slot,
    select_moments,
)
from causal_chain8.assemble_reel import assemble_reel  # noqa: E402
from causal_chain8.build_highlights import _moment_to_candidate  # noqa: E402
from causal_chain8.refine import build_refined_chain, classify_candidate_chain4  # noqa: E402
from eval_common import (  # noqa: E402
    REPORTS,
    ROOT as _ROOT,
    load_index,
    load_timeline_events,
    make_match_pbar,
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


def _ensure_min_moments(
    events: Sequence[Dict[str, Any]],
    selected: List[Any],
    *,
    min_clips: int,
) -> tuple[List[Any], Dict[str, Any]]:
    """在 PDF select_moments 结果上，用剩余 T1/T2 补到 min_clips（交付观感保底）。"""
    info: Dict[str, Any] = {
        "min_clips": min_clips,
        "n_before": len(selected),
        "n_filled": 0,
        "presentation_fill": False,
    }
    if min_clips <= 0 or len(selected) >= min_clips:
        info["n_after"] = len(selected)
        return list(selected), info

    times = [int(e["t_ms"]) for e in events]
    if not times:
        info["n_after"] = len(selected)
        return list(selected), info
    t_min, t_max = times[0], times[-1]
    half_ms = HALF_MS_DEFAULT if t_max >= HALF_MS_DEFAULT else max(t_max // 2, 1)
    used: Set[int] = {int(m.t_ms) for m in selected}

    t0 = collect_t0(events, times, half_ms, t_min, t_max)
    t0_times = {m.t_ms for m in t0}
    t1_all = collect_valuable_t1(events, times, half_ms, t_min, t_max, exclude_t_ms=t0_times)
    t2_all = collect_valuable_t2(events, times, half_ms, t_min, t_max, exclude_t_ms=t0_times)

    # 先 T1 后 T2；按槽位挑，避开已选时刻
    extras: List[Any] = []
    for pool in (t1_all, t2_all):
        cand = [m for m in pool if int(m.t_ms) not in used]
        picked = pick_per_slot(cand, half_ms, per_half=3)
        picked = dedupe_near(picked, T1_NEAR_DUP_MS)
        for m in picked:
            if len(selected) + len(extras) >= min_clips:
                break
            if any(abs(int(m.t_ms) - u) < T1_NEAR_DUP_MS for u in used):
                continue
            extras.append(m)
            used.add(int(m.t_ms))
        if len(selected) + len(extras) >= min_clips:
            break

    # 仍不够：按时间顺序从剩余池再贪心补
    if len(selected) + len(extras) < min_clips:
        rest = sorted(
            [m for m in (t1_all + t2_all) if int(m.t_ms) not in used],
            key=lambda m: m.t_ms,
        )
        for m in rest:
            if len(selected) + len(extras) >= min_clips:
                break
            if any(abs(int(m.t_ms) - u) < T1_NEAR_DUP_MS for u in used):
                continue
            extras.append(m)
            used.add(int(m.t_ms))

    out = list(selected) + extras
    out = merge_overlapping(out, 2_000)
    out.sort(key=lambda m: m.t_ms)
    info["n_filled"] = max(0, len(out) - info["n_before"])
    info["presentation_fill"] = info["n_filled"] > 0
    info["n_after"] = len(out)
    return out, info


def _moments_to_clips(
    events: List[Dict[str, Any]],
    moments: List[Any],
    *,
    match_id: str,
    profile: Dict[str, Any],
    model=None,
    processor=None,
    device: str = "cpu",
    max_new_tokens: int = 512,
) -> tuple[List[Any], Dict[str, Any]]:
    built: List[Any] = []
    fast_n = 0
    for i, moment in enumerate(moments):
        cand = _moment_to_candidate(events, moment, idx=i)
        tid, conf, margin, fast_path, _tr = classify_candidate_chain4(
            model,
            processor,
            events,
            cand,
            profile=profile,
            device=device,
            max_new_tokens=max_new_tokens,
            match_id=match_id,
        )
        if fast_path:
            fast_n += 1
        chain = build_refined_chain(
            clip_id=f"clip{i:02d}",
            events=events,
            candidate=cand,
            template_id=tid,
            confidence=conf,
            margin=margin,
            fast_path=fast_path,
            profile=profile,
            model=model,
            processor=processor,
            device=device,
            use_llm_narrative=False,
        )
        chain.t0_ms = moment.t0_ms
        chain.t1_ms = moment.t1_ms
        chain.validation = dict(chain.validation or {})
        chain.validation["selection"] = moment.to_dict()
        built.append(chain)
    final = assemble_reel(built)
    for j, c in enumerate(final):
        c.clip_id = f"clip{j:02d}"
    return final, {"moments_selected": len(moments), "clips_final": len(final), "fast_path": fast_n}


def main(argv: List[str] | None = None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="Dump full-rule highlight reels (min clips)")
    ap.add_argument("--limit-matches", type=int, default=0)
    ap.add_argument("--profile", default="production")
    ap.add_argument("--out-dir", type=Path, default=REPORTS / "reels_dump_full")
    ap.add_argument(
        "--min-clips",
        type=int,
        default=4,
        help="交付保底片段数；不足则用剩余 T1/T2 补（默认 4；可设 6）",
    )
    ap.add_argument("--use-llm", action="store_true", default=False)
    ap.add_argument("--model-path", type=str, default="/data2/lpy1/Qwen2.5-VL")
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args(argv)

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

    out_dir = args.out_dir if args.out_dir.is_absolute() else _ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: List[Dict[str, Any]] = []
    pbar = make_match_pbar("Dump Full Reels", len(matches))
    try:
        for mi, meta in enumerate(matches):
            mdir = _ROOT / meta["dir"]
            safe = str(meta.get("safe_id") or f"m{mi}")
            mid = str(meta.get("match_id") or safe)
            timeline_path = mdir / "timeline.json"
            events = load_timeline_events(mdir)

            if not events:
                manifest.append(
                    {
                        "safe_id": safe,
                        "ok": False,
                        "reason": "empty_timeline",
                        "n_clips": 0,
                    }
                )
                pbar.update(1)
                continue

            moments, sel_stats = select_moments(events)
            n_raw = len(moments)
            moments, fill_info = _ensure_min_moments(
                events, moments, min_clips=int(args.min_clips)
            )
            clips, build_stats = _moments_to_clips(
                [dict(e) for e in events],
                moments,
                match_id=safe,
                profile=profile,
                model=model,
                processor=processor,
                device=args.device if args.use_llm else "cpu",
            )
            clip_dicts = [_clip_to_dict(c) for c in clips]
            ordering = [str(c.get("clip_id") or f"clip{i:02d}") for i, c in enumerate(clip_dicts)]
            total_dur = sum(
                max(int(c.get("t1_ms") or 0) - int(c.get("t0_ms") or 0), 0) for c in clip_dicts
            )
            under_min = len(clips) < int(args.min_clips)
            payload = {
                "match_id": mid,
                "safe_id": safe,
                "input_file": str(timeline_path),
                "event_count": len(events),
                "reel": {
                    "clips": clip_dicts,
                    "ordering": ordering,
                    "total_duration_ms": total_dur,
                },
                "config": {
                    "backend": "dump_highlight_reels_full",
                    "profile": args.profile,
                    "drop_t2": False,
                    "min_clips": int(args.min_clips),
                    "use_llm": bool(args.use_llm),
                    "pipeline": "select_moments(full PDF)→optional T1/T2 fill→classify/refine",
                    "note": "交付观感用；评测 no_t2 仍用 dump_highlight_reels.py / reels_dump",
                },
                "stats": {
                    **build_stats,
                    "select": sel_stats,
                    "fill": fill_info,
                    "n_moments_raw": n_raw,
                    "under_min_clips": under_min,
                },
            }
            out_path = out_dir / f"{safe[:60]}.json"
            write_reel_json(out_path, payload)
            manifest.append(
                {
                    "safe_id": safe,
                    "match_id": mid,
                    "ok": True,
                    "path": str(out_path.relative_to(_ROOT)),
                    "n_events": len(events),
                    "n_clips_raw": n_raw,
                    "n_clips": len(clips),
                    "n_filled": fill_info.get("n_filled"),
                    "presentation_fill": fill_info.get("presentation_fill"),
                    "under_min_clips": under_min,
                    "rule": sel_stats.get("rule"),
                    "n_t0": sel_stats.get("n_t0"),
                    "n_t1_pool": sel_stats.get("n_t1_pool"),
                    "n_t2_pool": sel_stats.get("n_t2_pool"),
                    "total_duration_ms": total_dur,
                }
            )
            pbar.set_postfix_str(
                f"raw={n_raw}→{len(clips)} rule={str(sel_stats.get('rule'))[:18]}"
            )
            pbar.update(1)
    finally:
        pbar.close()

    n_ok = sum(1 for m in manifest if m.get("ok"))
    n_under = sum(1 for m in manifest if m.get("under_min_clips"))
    n_one = sum(1 for m in manifest if (m.get("n_clips") or 0) <= 1)
    summary = {
        "n_matches": len(matches),
        "n_ok": n_ok,
        "n_fail": len(matches) - n_ok,
        "min_clips": int(args.min_clips),
        "n_under_min_clips": n_under,
        "n_clips_le_1": n_one,
        "out_dir": str(out_dir),
        "use_llm": bool(args.use_llm),
        "drop_t2": False,
        "matches": manifest,
    }
    man_path = out_dir / "_manifest.json"
    man_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "n_matches",
                    "n_ok",
                    "min_clips",
                    "n_under_min_clips",
                    "n_clips_le_1",
                    "out_dir",
                )
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    print(f"wrote {man_path}", flush=True)
    return summary


if __name__ == "__main__":
    main()
