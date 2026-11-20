"""timeline_highlights 结果可视化：proposal 时间轴 + 每段 GNN 18 类概率。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# 非交互后端，便于服务器无 DISPLAY 环境
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib import font_manager


def _setup_cjk_font() -> None:
    """尽量加载系统中文字体，避免中文标题方框。"""
    for name in (
        "Noto Sans CJK SC",
        "WenQuanYi Micro Hei",
        "SimHei",
        "Microsoft YaHei",
        "Arial Unicode MS",
    ):
        try:
            font_manager.fontManager.addfont(
                font_manager.findfont(name, fallback_to_default=False)
            )
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return
        except Exception:
            continue
    plt.rcParams["axes.unicode_minus"] = False


def _ms_to_min(t_ms: int) -> float:
    return t_ms / 60_000.0


def _load_result(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def plot_timeline_overview(
    result: Dict[str, Any],
    events: List[Dict[str, Any]],
    out_path: Path,
) -> None:
    """
    时间轴总览：事件点 + 锚点/滑窗 proposal 条带 + 最终 clip 高亮。
    """
    _setup_cjk_font()
    proposals = result.get("proposals") or {}
    clips = result.get("clips") or []

    fig, ax = plt.subplots(figsize=(14, 5))
    t_min = min(int(e["t_ms"]) for e in events)
    t_max = max(int(e["t_ms"]) for e in events)
    pad = max((t_max - t_min) * 0.02, 60_000)
    xmin, xmax = t_min - pad, t_max + pad

    # 事件点
    for i, e in enumerate(events):
        t = int(e["t_ms"])
        ax.scatter(
            _ms_to_min(t),
            0,
            s=40,
            c="#333333",
            zorder=5,
            marker="|",
        )
        if len(events) <= 30:
            ax.annotate(
                e["type"],
                (_ms_to_min(t), 0.08),
                fontsize=7,
                rotation=45,
                ha="left",
            )

    y_anchor_geom, y_anchor_scored = 3.0, 2.0
    y_slide_geom, y_slide_scored = 1.0, 0.0
    y_final = 4.0

    def draw_spans(
        items: List[Dict[str, Any]],
        y: float,
        color: str,
        alpha: float,
        height: float = 0.35,
        label_prefix: str = "",
    ) -> None:
        for it in items:
            t0, t1 = int(it["t0_ms"]), int(it["t1_ms"])
            ax.barh(
                y,
                _ms_to_min(t1) - _ms_to_min(t0),
                left=_ms_to_min(t0),
                height=height,
                color=color,
                alpha=alpha,
                edgecolor="white",
                linewidth=0.5,
            )
            pid = it.get("proposal_id", "")
            if pid and (t1 - t0) > (xmax - xmin) * 0.05:
                ax.text(
                    _ms_to_min((t0 + t1) / 2),
                    y,
                    pid,
                    ha="center",
                    va="center",
                    fontsize=6,
                    color="black",
                )

    draw_spans(
        proposals.get("anchor_geom", []),
        y_anchor_geom,
        "#f4a582",
        0.45,
        label_prefix="ag",
    )
    draw_spans(
        proposals.get("anchor_scored", []),
        y_anchor_scored,
        "#d6604d",
        0.7,
    )
    if proposals.get("sliding_geom"):
        draw_spans(
            proposals.get("sliding_geom", []),
            y_slide_geom,
            "#92c5de",
            0.45,
        )
        draw_spans(
            proposals.get("sliding_scored", []),
            y_slide_scored,
            "#4393c3",
            0.7,
        )
    draw_spans(clips, y_final, "#1a9850", 0.85, height=0.45)

    ax.set_xlim(_ms_to_min(xmin), _ms_to_min(xmax))
    ax.set_ylim(-0.6, 4.6)
    ax.set_xlabel("比赛时间 (分钟，由 t_ms/60000)")
    ytick_pos = [
        y_slide_scored,
        y_slide_geom,
        y_anchor_scored,
        y_anchor_geom,
        y_final,
    ]
    ytick_lbl = [
        "滑窗 scored",
        "滑窗 geom",
        "锚点 scored",
        "锚点 geom",
        "最终 clips",
    ]
    if not proposals.get("sliding_geom"):
        ytick_pos = [y_anchor_scored, y_anchor_geom, y_final]
        ytick_lbl = ["锚点 scored", "锚点 geom", "最终 clips"]
    ax.set_yticks(ytick_pos)
    ax.set_yticklabels(ytick_lbl)
    ax.set_title("Proposal 时间轴（geom=几何窗, scored=GNN 打分后）")
    ax.grid(axis="x", alpha=0.3)

    legend = [
        mpatches.Patch(color="#f4a582", alpha=0.6, label="锚点几何 proposal"),
        mpatches.Patch(color="#d6604d", alpha=0.8, label="锚点 GNN scored"),
        mpatches.Patch(color="#92c5de", alpha=0.6, label="滑窗几何 proposal"),
        mpatches.Patch(color="#4393c3", alpha=0.8, label="滑窗 GNN scored"),
        mpatches.Patch(color="#1a9850", alpha=0.9, label="最终入选 clip"),
    ]
    ax.legend(handles=legend, loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_proposal_prob_bars(
    proposal: Dict[str, Any],
    out_path: Path,
    *,
    title_suffix: str = "",
) -> None:
    """单条 proposal：18 模版概率横向条形图。"""
    _setup_cjk_font()
    probs: Dict[str, float] = proposal.get("probs") or {}
    if not probs:
        # 仅几何段、尚未 GNN
        fig, ax = plt.subplots(figsize=(8, 2))
        ax.text(0.5, 0.5, "无 GNN probs（仅几何 proposal）", ha="center", va="center")
        ax.axis("off")
        fig.savefig(out_path, dpi=120)
        plt.close(fig)
        return

    items = sorted(probs.items(), key=lambda x: -x[1])
    labels = [k for k, _ in items]
    vals = [v for _, v in items]
    colors = ["#d73027" if i == 0 else "#4575b4" for i in range(len(vals))]

    fig, ax = plt.subplots(figsize=(10, max(4, len(labels) * 0.22)))
    y_pos = range(len(labels))
    ax.barh(list(y_pos), vals, color=colors, alpha=0.85)
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_xlim(0, 1.05)
    ax.set_xlabel("GNN softmax 概率")
    pid = proposal.get("proposal_id", "?")
    src = proposal.get("source", "")
    tid = proposal.get("pred_chain_template_id", "")
    zh = proposal.get("pred_chain_label_zh", tid)
    m = proposal.get("margin", 0)
    p1 = proposal.get("prob_top1", 0)
    flags = []
    if proposal.get("passes_margin"):
        flags.append("pass_margin")
    if proposal.get("in_final_clips"):
        flags.append("FINAL")
    elif proposal.get("in_anchor_selected"):
        flags.append("anchor_sel")
    elif proposal.get("in_sliding_selected"):
        flags.append("slide_sel")
    flag_s = ",".join(flags) if flags else "filtered_out"
    ax.set_title(
        f"{pid} [{src}] {zh}\n"
        f"top1={tid} p1={p1:.3f} margin={m:.3f} | {flag_s}{title_suffix}",
        fontsize=9,
    )
    ax.axvline(1.0 / len(vals), color="gray", linestyle="--", alpha=0.5, label="均匀基线")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_all_proposals_grid(
    result: Dict[str, Any],
    out_path: Path,
    *,
    max_rows: int = 24,
) -> None:
    """所有带 GNN 的 proposal 概率汇总大图（条形，每行一个 proposal）。"""
    _setup_cjk_font()
    proposals = result.get("proposals") or {}
    rows: List[Dict[str, Any]] = []
    for key in ("anchor_scored", "sliding_scored"):
        for p in proposals.get(key, []):
            if p.get("probs"):
                rows.append(p)
    rows.sort(key=lambda x: (x.get("source", ""), int(x.get("t0_ms", 0))))
    if not rows:
        return
    rows = rows[:max_rows]
    n = len(rows)
    template_ids = sorted(
        {tid for p in rows for tid in (p.get("probs") or {}).keys()}
    )
    mat = []
    for p in rows:
        pr = p.get("probs") or {}
        mat.append([pr.get(t, 0.0) for t in template_ids])

    fig, ax = plt.subplots(figsize=(12, max(4, n * 0.35)))
    im = ax.imshow(mat, aspect="auto", cmap="YlOrRd", vmin=0, vmax=1)
    ax.set_xticks(range(len(template_ids)))
    ax.set_xticklabels(template_ids, rotation=60, ha="right", fontsize=6)
    ylabels = []
    for p in rows:
        pid = p.get("proposal_id", "")
        mark = "*" if p.get("in_final_clips") else ""
        ylabels.append(f"{mark}{pid} {p.get('pred_chain_template_id','')[:12]}")
    ax.set_yticks(range(n))
    ax.set_yticklabels(ylabels, fontsize=7)
    ax.set_title("全部 GNN scored proposals × 18 模版概率（*=最终 clip）")
    fig.colorbar(im, ax=ax, label="prob")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def render_visualizations(
    result: Dict[str, Any],
    events: List[Dict[str, Any]],
    viz_dir: Path,
) -> List[Path]:
    """写入 viz_dir 下 PNG，返回路径列表。"""
    viz_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []

    p1 = viz_dir / "01_timeline_overview.png"
    plot_timeline_overview(result, events, p1)
    written.append(p1)

    p2 = viz_dir / "02_all_proposals_heatmap.png"
    plot_all_proposals_grid(result, p2)
    written.append(p2)

    proposals = result.get("proposals") or {}
    prob_dir = viz_dir / "proposals_gnn_probs"
    prob_dir.mkdir(parents=True, exist_ok=True)
    for key in ("anchor_scored", "sliding_scored"):
        for p in proposals.get(key, []):
            pid = p.get("proposal_id", "unknown")
            outp = prob_dir / f"{pid}_{key}.png"
            plot_proposal_prob_bars(p, outp)
            written.append(outp)

    # 几何-only（未单独 scored 的滑窗 geom 若存在）
    geom_dir = viz_dir / "proposals_geom_only"
    for key in ("anchor_geom", "sliding_geom"):
        scored_ids = {
            x.get("proposal_id")
            for x in proposals.get(key.replace("geom", "scored"), [])
        }
        for p in proposals.get(key, []):
            pid = p.get("proposal_id")
            if pid in scored_ids:
                continue
            geom_dir.mkdir(parents=True, exist_ok=True)
            outp = geom_dir / f"{pid}_{key}.png"
            plot_proposal_prob_bars(p, outp)
            written.append(outp)

    summary = viz_dir / "README.txt"
    summary.write_text(
        "可视化输出说明\n"
        "01_timeline_overview.png — 事件点与锚点/滑窗/最终 clip 时间条带\n"
        "02_all_proposals_heatmap.png — 所有 GNN scored proposal 的概率热力图\n"
        "proposals_gnn_probs/ — 每条 scored proposal 的 18 类条形图\n",
        encoding="utf-8",
    )
    written.append(summary)
    return written


def visualize_from_json(
    highlights_json: Path,
    timeline_json: Path,
    viz_dir: Path,
) -> List[Path]:
    from causal_chain2.timeline_io import load_timeline_json

    result = _load_result(highlights_json)
    events = load_timeline_json(timeline_json)
    return render_visualizations(result, events, viz_dir)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(
        description="从 highlights.json 生成 proposal 时间轴与 GNN 概率可视化"
    )
    ap.add_argument("--highlights-json", type=Path, required=True)
    ap.add_argument("--timeline-json", type=Path, required=True)
    ap.add_argument("--viz-dir", type=Path, required=True)
    args = ap.parse_args()
    paths = visualize_from_json(
        args.highlights_json, args.timeline_json, args.viz_dir
    )
    print(f"wrote {len(paths)} files -> {args.viz_dir}")


if __name__ == "__main__":
    main()
