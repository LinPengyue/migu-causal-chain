"""Prepare a single-goal paid VLM first-live verification pack (no HTTP).

Does not call any paid API. Writes a reviewable JSON describing frames, PTS,
model, cost ceiling, and prompt for operator approval.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .first_live_localize import extract_frame_accurate
from .pipeline import dump


# Prefer configured Paratera VLM; do not default to OpenAI gpt-*.
import os as _os

DEFAULT_MODEL = (
    (_os.environ.get("STORY_VLM_MODEL") or "").strip() or "Qwen3.6-Plus"
)
# Conservative per-call estimate for dense vision with ~8 frames.
DEFAULT_USD_PER_CALL = 0.04
DEFAULT_MAX_CALLS = 2
DEFAULT_COST_CEILING_USD = 0.10


PROMPT_TEMPLATE = """You are verifying whether a football goal clip is the FIRST LIVE broadcast
of the goal action (not a replay / slow-mo / celebration-only / scoreboard-only).

Segment: {segment_id}
Role: {role}
Source media window: [{media_in:.3f}, {media_out:.3f}] seconds
Goal action PTS (recovery): {goal_action_sec}
Score confirmation PTS: {score_confirmation_sec}
Score before → after: {score_before} → {score_after}

For the provided frames (in story/source order), answer JSON only:
{{
  "observed_shot": true|false|null,
  "observed_net": true|false|null,
  "live_or_replay": "live"|"replay"|"unknown",
  "slow_motion_or_replay_graphics": true|false|null,
  "scoreboard_only": true|false|null,
  "attacking_side_consistent": true|false|null,
  "first_live_judgment": "FIRST_LIVE_VERIFIED"|"POSSIBLE_FIRST_LIVE"|"REPLAY_DETECTED"|"UNRESOLVED",
  "evidence": "short rationale citing frame indices",
  "cannot_certify_without_more_frames": true|false
}}

Rules:
- Do NOT mark FIRST_LIVE_VERIFIED unless shot+net are visible AND continuous live (not replay).
- Scoreboard flip alone is never FIRST_LIVE_VERIFIED.
- If unsure, return UNRESOLVED or POSSIBLE_FIRST_LIVE.
"""


def prepare_single_goal_vlm_pack(
    *,
    video: Path,
    segment_id: str,
    role: str,
    media_in: float,
    media_out: float,
    out_dir: Path,
    goal_action_sec: Optional[float] = None,
    score_confirmation_sec: Optional[float] = None,
    score_before: Any = None,
    score_after: Any = None,
    model: str = DEFAULT_MODEL,
    max_calls: int = DEFAULT_MAX_CALLS,
    usd_per_call: float = DEFAULT_USD_PER_CALL,
    cost_ceiling_usd: float = DEFAULT_COST_CEILING_USD,
    n_frames: int = 8,
) -> Dict[str, Any]:
    dest = Path(out_dir)
    frames_dir = dest / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    mi, mo = float(media_in), float(media_out)
    if mo <= mi:
        raise ValueError("empty media window")
    span = mo - mi
    ts = [mi + (i + 0.5) * span / n_frames for i in range(n_frames)]
    frame_rows: List[Dict[str, Any]] = []
    for i, t in enumerate(ts):
        fp = frames_dir / f"{segment_id}_f{i:02d}_{int(t * 1000)}.jpg"
        fr = extract_frame_accurate(Path(video), t, fp)
        frame_rows.append({
            "index": i,
            "media_sec": round(t, 3),
            "path": fr.get("path") if fr.get("ok") else None,
            "ok": bool(fr.get("ok")),
        })

    est_calls = int(max_calls)
    est_cost = round(est_calls * float(usd_per_call), 4)
    prompt = PROMPT_TEMPLATE.format(
        segment_id=segment_id,
        role=role,
        media_in=mi,
        media_out=mo,
        goal_action_sec=goal_action_sec,
        score_confirmation_sec=score_confirmation_sec,
        score_before=score_before,
        score_after=score_after,
    )
    pack = {
        "schema": "v3a_paid_first_live_prep_v1",
        "paid_call_authorized": False,
        "http_executed": False,
        "segment_id": segment_id,
        "role": role,
        "source_video": str(video),
        "source_pts": {"media_in": mi, "media_out": mo},
        "goal_action_sec": goal_action_sec,
        "score_confirmation_sec": score_confirmation_sec,
        "score_before": score_before,
        "score_after": score_after,
        "frames": frame_rows,
        "n_frames_ok": sum(1 for f in frame_rows if f.get("ok")),
        "model": model,
        "estimated_http_calls": est_calls,
        "estimated_usd_per_call": usd_per_call,
        "estimated_cost_usd": est_cost,
        "cost_ceiling_usd": cost_ceiling_usd,
        "within_ceiling": est_cost <= float(cost_ceiling_usd) + 1e-9,
        "verification_prompt": prompt,
        "note": (
            "Pack only. Do not call paid API until operator confirms model, "
            "call count, and cost ceiling."
        ),
    }
    dump(dest / "paid_first_live_prep.json", pack)
    return pack
