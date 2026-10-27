"""生产路径集锦构建：直接调用 causal_chain8，不读 gold/评测真值。

与 `eval_common.build_highlight_clips` 同源（select_moments → classify → refine → assemble），
但本模块不依赖 eval/，也不接触任何 gold/label 字段。

相对 `causal_chain8.build_highlights.run_build_highlights`：
- run_build_highlights 从 timeline 文件加载（可含 ground_truth_chains 仅用于 stats，不参与选片分类）
- 本函数吃内存 events 列表，跳过文件 IO / GT 匹配，适合 HTTP end 路径
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple


def build_highlight_clips_from_events(
    events: Sequence[Dict[str, Any]],
    *,
    match_id: str,
    profile: Dict[str, Any],
    model=None,
    processor=None,
    device: str = "cpu",
    max_new_tokens: int = 512,
    drop_t2: bool = False,
) -> Tuple[List[Any], Dict[str, Any]]:
    from causal_chain8.assemble_reel import assemble_reel
    from causal_chain8.build_highlights import _moment_to_candidate
    from causal_chain8.refine import build_refined_chain, classify_candidate_chain4
    from causal_chain8.select_moments import select_moments

    evs = [dict(e) for e in events]
    if not evs:
        return [], {"moments_selected": 0, "clips_final": 0}

    moments, select_stats = select_moments(evs)
    if drop_t2:
        moments = [m for m in moments if m.tier != "T2"]
        select_stats = dict(select_stats)
        select_stats["drop_t2"] = True

    built: List[Any] = []
    fast_n = 0
    for i, moment in enumerate(moments):
        cand = _moment_to_candidate(evs, moment, idx=i)
        tid, conf, margin, fast_path, _tr = classify_candidate_chain4(
            model,
            processor,
            evs,
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
            events=evs,
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
        # clip_id 仅算法内部编号；对外 callback 必须用业务 clipId（adapters 负责）
        chain.t0_ms = moment.t0_ms
        chain.t1_ms = moment.t1_ms
        chain.validation = dict(chain.validation or {})
        chain.validation["selection"] = moment.to_dict()
        built.append(chain)

    final = assemble_reel(built)
    for j, c in enumerate(final):
        c.clip_id = f"clip{j:02d}"
    stats = {
        "moments_selected": len(moments),
        "clips_final": len(final),
        "fast_path": fast_n,
        "select": select_stats,
        "source": "api.highlight_build → causal_chain8 (no gold)",
    }
    return final, stats
