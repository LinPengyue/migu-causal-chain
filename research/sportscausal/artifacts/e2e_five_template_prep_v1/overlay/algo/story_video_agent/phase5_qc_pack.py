"""Phase 5.1: lens-level QC evidence pack (offline frames, no paid VLM).

Extracts stills around goal anchors / scoreboards / ending for human review.
Does NOT claim semantic verification pass.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def _ffmpeg() -> str:
    return "ffmpeg"


def grab_frame(video: Path, t_sec: float, out_jpg: Path) -> Dict[str, Any]:
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _ffmpeg(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{max(0.0, t_sec):.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(out_jpg),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
    return {
        "t_sec": t_sec,
        "path": str(out_jpg),
        "ok": proc.returncode == 0 and out_jpg.is_file(),
        "stderr_tail": (proc.stderr or "")[-200:],
    }


def build_qc_pack(
    *,
    video: Path,
    delivery_edl: List[Dict[str, Any]],
    out_dir: Path,
    match_label: str,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    checks: List[Dict[str, Any]] = []

    focus_roles = (
        "opponent_opening_goal_action",
        "equalizer_goal_action",
        "go_ahead_goal_action",
        "lead_extend",
        "ending",
        "deficit_scoreboard",
    )

    for row in delivery_edl:
        role = str(row.get("role") or "")
        if not any(k in role for k in focus_roles):
            continue
        tin = row.get("media_in")
        tout = row.get("media_out")
        if tin is None or tout is None:
            continue
        tin_f, tout_f = float(tin), float(tout)
        anchor = row.get("goal_anchor_t_sec")
        samples = [
            ("in_plus_1", tin_f + 1.0),
            ("mid", (tin_f + tout_f) / 2.0),
            ("out_minus_1", max(tin_f, tout_f - 1.0)),
        ]
        if anchor is not None:
            samples.append(("anchor", float(anchor)))
            samples.append(("anchor_plus_1_5", float(anchor) + 1.5))

        frame_recs = []
        for tag, t in samples:
            if t < tin_f - 0.05 or t > tout_f + 0.05:
                # still grab anchor even if outside — marks integrity issue
                if tag.startswith("anchor"):
                    pass
                else:
                    continue
            jpg = frames_dir / f"{row.get('segment_id')}_{tag}_{t:.1f}.jpg"
            frame_recs.append(grab_frame(video, t, jpg))

        checks.append(
            {
                "segment_id": row.get("segment_id"),
                "beat": row.get("beat"),
                "role": role,
                "media_in": tin_f,
                "media_out": tout_f,
                "goal_anchor_t_sec": anchor,
                "goal_action_complete": row.get("goal_action_complete"),
                "integrity_failure": row.get("integrity_failure"),
                "event_ids": row.get("event_ids"),
                "time_status": row.get("time_status"),
                "shot_kind": row.get("shot_kind"),
                "is_replay": row.get("is_replay"),
                "checklist": {
                    "goal_inside_window": (
                        None
                        if anchor is None
                        else (tin_f <= float(anchor) <= tout_f)
                    ),
                    "not_scoreboard_as_goal": "scoreboard" not in role
                    or "goal_action" not in role,
                    "glitch_demotion": row.get("goal_action_complete") is not False
                    or bool(row.get("integrity_failure")),
                    "semantic_verified": False,
                    "human_review_required": True,
                },
                "frames": frame_recs,
            }
        )

    md_lines = [
        f"# QC 证据包：{match_label}",
        "",
        "> 自动抽帧仅供人工审片。**不构成**语义核验通过。`render_ready` 仍为 false。",
        "",
        "## 检查项说明",
        "- 进球锚点是否落在裁剪窗口内",
        "- 是否误用比分牌/回放充当进球直播（需看图）",
        "- 是否保留进攻上下文（需看图）",
        "- 花屏避让是否破坏进球完整性（见 goal_action_complete）",
        "- Summary / Graph / EDL / 视频一致性（对照同目录产物）",
        "",
    ]
    for c in checks:
        md_lines.append(f"### {c['segment_id']} · {c['role']}")
        md_lines.append(
            f"- 窗口 `{c['media_in']:.3f}`–`{c['media_out']:.3f}` · "
            f"anchor={c['goal_anchor_t_sec']} · complete={c['goal_action_complete']}"
        )
        md_lines.append(f"- checklist: `{json.dumps(c['checklist'], ensure_ascii=False)}`")
        md_lines.append(f"- integrity: `{c['integrity_failure']}`")
        for fr in c["frames"]:
            status = "OK" if fr["ok"] else "FAIL"
            md_lines.append(f"- [{status}] t={fr['t_sec']:.2f} → `{fr['path']}`")
        md_lines.append("")

    report = {
        "match_label": match_label,
        "video": str(video),
        "n_checks": len(checks),
        "semantic_verified": False,
        "render_ready": False,
        "checks": checks,
    }
    (out_dir / "qc_pack.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "qc_pack.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return report


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--edl", type=Path, required=True, help="candidate_edl.json")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--label", type=str, default="match")
    args = p.parse_args(argv)
    edl = json.loads(args.edl.read_text(encoding="utf-8"))
    if isinstance(edl, dict):
        edl = edl.get("candidate_edl") or edl.get("rows") or []
    rep = build_qc_pack(
        video=args.video, delivery_edl=edl, out_dir=args.out_dir, match_label=args.label
    )
    print(json.dumps({"n_checks": rep["n_checks"], "out": str(args.out_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
