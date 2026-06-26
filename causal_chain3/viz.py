"""集锦因果链 reel 可视化。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _setup_font() -> None:
    try:
        from matplotlib import font_manager

        for p in (
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        ):
            if Path(p).is_file():
                font_manager.fontManager.addfont(p)
                plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
                break
    except Exception:
        pass
    plt.rcParams["axes.unicode_minus"] = False


def render_reel_visualizations(
    reel_dict: Dict[str, Any],
    events: List[Dict[str, Any]],
    out_dir: Path,
) -> List[Path]:
    _setup_font()
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []

    clips = reel_dict.get("reel", {}).get("clips", [])
    if not events:
        return paths

    t_max = max(int(e["t_ms"]) for e in events)
    fig, ax = plt.subplots(figsize=(14, max(4, len(clips) * 0.5 + 2)))
    ax.set_title(f"Highlight Reel — {reel_dict.get('match_id', '')}")
    ax.set_xlabel("t_ms")
    ax.set_ylabel("clip")

    for i, c in enumerate(clips):
        t0, t1 = int(c["t0_ms"]), int(c["t1_ms"])
        label = c.get("chain_label_zh", c.get("chain_template_id", ""))
        ax.barh(i, t1 - t0, left=t0, height=0.6, alpha=0.75)
        ax.text(t0, i, f" {label}", va="center", fontsize=8)

    # 全场事件散点
    for e in events:
        if e["type"] in ("match_start", "match_end", "substitution", "pass"):
            continue
        ax.scatter(int(e["t_ms"]), -1, s=8, c="gray", alpha=0.5)

    ax.set_yticks(range(len(clips)))
    ax.set_yticklabels([c.get("clip_id", str(i)) for i, c in enumerate(clips)])
    ax.set_xlim(0, t_max * 1.02)
    ax.axhline(-0.5, color="lightgray", linewidth=0.5)
    fig.tight_layout()
    p0 = out_dir / "01_reel_timeline.png"
    fig.savefig(p0, dpi=120)
    plt.close(fig)
    paths.append(p0)

    # 每条链的事件类型条
    for c in clips:
        cid = c.get("clip_id", "clip")
        evs = c.get("events", [])
        if not evs:
            continue
        fig, ax = plt.subplots(figsize=(10, 1.8))
        types = [e["type"] for e in evs]
        times = [int(e["t_ms"]) for e in evs]
        t0 = min(times)
        for j, (t, tp) in enumerate(zip(times, types)):
            ax.barh(0, max(times[j] - t0, 1) if j == 0 else times[j] - times[j - 1],
                    left=t - t0 if j == 0 else times[j - 1] - t0, height=0.5, alpha=0.7)
            ax.text(t - t0, 0, tp, ha="center", va="center", fontsize=7, rotation=45)
        ax.set_title(f"{cid}: {c.get('chain_label_zh', '')}\n{c.get('narrative_zh', '')}")
        ax.set_yticks([])
        ax.set_xlabel("relative t_ms")
        fig.tight_layout()
        p = out_dir / f"chain_{cid}.png"
        fig.savefig(p, dpi=100)
        plt.close(fig)
        paths.append(p)

    readme = out_dir / "README.txt"
    readme.write_text(
        "causal_chain3 reel visualizations\n"
        + "\n".join(str(x.name) for x in paths)
        + "\n",
        encoding="utf-8",
    )
    return paths
