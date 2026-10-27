"""可选：按 segment 时间从比赛视频抽帧，供 Qwen2.5-VL 补充分析。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from causal_chain2.llm_json import extract_json_object
from causal_chain2.llm_qwen import generate_text

from causal_chain8.io.eval_record import EvalRecord
from causal_chain8.llm.prompts import SYSTEM_AGENT_V4, prompt_vlm_supplement


@dataclass
class VlmClipResult:
    suggested_template_id: str = ""
    confidence: float = 0.0
    visible_outcome: str = ""
    conflict_with_annotation: bool = False
    note: str = ""
    clip_path: str = ""
    skipped_reason: str = ""


def _parse_sketch(s: str) -> tuple[float, float] | None:
    """解析 20:07-20:20 或 0:41-1:33 形式为秒。"""
    s = str(s).strip()
    m = re.match(r"(\d+):(\d+)\s*[-~]\s*(\d+):(\d+)", s)
    if not m:
        return None

    def to_sec(mm: str, ss: str) -> float:
        return int(mm) * 60 + int(ss)

    return to_sec(m.group(1), m.group(2)), to_sec(m.group(3), m.group(4))


def _resolve_video(rec: EvalRecord, video_root: Optional[str]) -> Optional[Path]:
    name = str(rec.meta.get("video_name", "")).strip()
    if not name:
        return None
    if video_root:
        p = Path(video_root) / name
        if p.is_file():
            return p
    return None


def analyze_clip_optional(
    rec: EvalRecord,
    *,
    model,
    processor,
    device: str,
    video_root: Optional[str],
    rule_top3: List[str],
    max_frames: int = 3,
    max_new_tokens: int = 512,
) -> VlmClipResult:
    video = _resolve_video(rec, video_root)
    sketch = str(rec.meta.get("segment_time_sketch", ""))
    if not video:
        return VlmClipResult(skipped_reason="video_not_found")
    if not sketch:
        return VlmClipResult(skipped_reason="no_segment_time")

    span = _parse_sketch(sketch)
    if not span:
        return VlmClipResult(skipped_reason=f"bad_segment_time:{sketch}")

    try:
        import cv2  # type: ignore
    except ImportError:
        return VlmClipResult(skipped_reason="opencv_not_installed")

    start_s, end_s = span
    mid = (start_s + end_s) / 2
    times = [start_s, mid, end_s][: max(1, max_frames)]

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return VlmClipResult(skipped_reason="video_open_failed")

    frames = []
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if ok:
            frames.append(frame)
    cap.release()
    if not frames:
        return VlmClipResult(skipped_reason="no_frames_extracted")

    # 当前 llm_qwen.generate_text 为纯文本；VLM 帧分析暂以文本 prompt + 元数据代替，
    # 后续可扩展为多模态 messages。
    text = generate_text(
        model,
        processor,
        SYSTEM_AGENT_V4,
        prompt_vlm_supplement(rec, rule_top3)
        + f"\n\n（注：视频 {video.name} @ {sketch}，已抽 {len(frames)} 帧，当前为文本回退模式）",
        device,
        max_new_tokens=max_new_tokens,
        do_sample=False,
    )
    obj = extract_json_object(text) or {}
    return VlmClipResult(
        suggested_template_id=str(obj.get("suggested_template_id", "")),
        confidence=float(obj.get("confidence", 0.0) or 0.0),
        visible_outcome=str(obj.get("visible_outcome", "")),
        conflict_with_annotation=bool(obj.get("conflict_with_annotation", False)),
        note=str(obj.get("note", "")),
        clip_path=str(video),
    )
