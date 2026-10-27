"""VLM 视觉理解：经远程 ApiProvider；时间戳由程序绑定，禁止模型生成可信时间。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from story_video_agent.api_provider import ApiProvider

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _extract_json_obj(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty VLM response")
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    fence = _JSON_FENCE.search(text)
    if fence:
        obj = json.loads(fence.group(1))
        if isinstance(obj, dict):
            return obj
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        obj = json.loads(text[start : end + 1])
        if isinstance(obj, dict):
            return obj
    raise ValueError("VLM response is not strict JSON object")


def _normalize_evidence(
    raw: Dict[str, Any],
    *,
    gap_id: str,
    frame_ids: Sequence[str],
    frame_bindings: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    allowed = set(frame_ids)
    cited = [str(x) for x in (raw.get("frame_ids") or raw.get("cited_frame_ids") or [])]
    cited = [c for c in cited if c in allowed] or list(frame_ids)
    stripped = [
        k
        for k in raw.keys()
        if k.lower() in ("timestamp", "time", "t_sec", "media_sec", "pts", "actual_time")
    ]
    return {
        "gap_id": gap_id,
        "observed_actions": list(raw.get("observed_actions") or raw.get("actions") or []),
        "possible_teams": list(raw.get("possible_teams") or raw.get("teams") or []),
        "story_relation": str(raw.get("story_relation") or raw.get("relation") or ""),
        "confidence": float(raw.get("confidence") or 0.0),
        "frame_ids": cited,
        "notes": str(raw.get("notes") or ""),
        "frame_time_bindings": [
            {
                "frame_id": b["frame_id"],
                "requested_media_sec": b.get("requested_media_sec"),
                "actual_media_sec": b.get("actual_media_sec"),
                "pts_status": b.get("pts_status"),
                "match_logic_sec": b.get("match_logic_sec"),
                "match_logic_status": b.get("match_logic_status"),
            }
            for b in frame_bindings
            if b.get("frame_id") in cited
        ],
        "provider_fields_stripped": stripped,
        "observation_only": True,
        "fact_verified": False,
    }


class VisionProvider:
    def __init__(self, api: Optional[ApiProvider] = None, *, force_mock: bool = False) -> None:
        self.api = api or ApiProvider(force_mock=force_mock)
        if force_mock:
            self.api.force_mock = True

    @property
    def info(self) -> Any:
        st = self.api.status()
        return type(
            "VisionInfo",
            (),
            {
                "available": st["vision_ready"],
                "kind": "openai_compatible" if st["vision_ready"] else "mock",
                "base_url": st["vision"]["base_url"],
                "model": st["vision"]["model"],
                "notes": st["notes"],
                "discovered": [],
                "to_dict": lambda self=None, _st=st: {
                    "available": _st["vision_ready"],
                    "kind": "openai_compatible" if _st["vision_ready"] else "mock",
                    "base_url": _st["vision"]["base_url"],
                    "model": _st["vision"]["model"],
                    "notes": _st["notes"],
                },
            },
        )()

    @property
    def stats(self) -> Any:
        usage = self.api.stats.summary()
        vision = usage.get("by_role", {}).get("vision", {})
        return type(
            "VS",
            (),
            {
                "calls": vision.get("calls", 0),
                "failures": usage.get("failures", 0),
                "elapsed_sec": usage.get("elapsed_sec", 0.0),
                "last_error": "",
                "to_dict": lambda self=None, u=usage, v=vision: {
                    "calls": v.get("calls", 0),
                    "failures": u.get("failures", 0),
                    "elapsed_sec": u.get("elapsed_sec", 0.0),
                    "tokens": v.get("tokens", 0),
                    "est_cost_usd": v.get("est_cost_usd", 0.0),
                },
            },
        )()

    def describe_frames(
        self,
        *,
        gap_id: str,
        gap_note: str,
        frame_paths: Sequence[Path],
        frame_ids: Sequence[str],
        frame_bindings: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        mock_obj = self._mock_obj(gap_id=gap_id, frame_ids=frame_ids, gap_note=gap_note)
        prompt = (
            "You are a sports broadcast vision assistant. "
            "Return ONE JSON object with keys: observed_actions (string[]), "
            "possible_teams (string[]), story_relation (string), confidence (0-1), "
            "frame_ids (subset of allowed ids), notes (string). "
            "Do NOT invent timestamps or media times; the program binds times. "
            f"gap_id={gap_id}. context={gap_note}. allowed_frame_ids={list(frame_ids)}."
        )
        try:
            raw_resp = self.api.vision_json(
                prompt=prompt,
                frame_paths=frame_paths,
                frame_ids=frame_ids,
                mock_obj=mock_obj,
            )
            raw = _extract_json_obj(str(raw_resp.get("content") or ""))
            evidence = _normalize_evidence(
                raw, gap_id=gap_id, frame_ids=frame_ids, frame_bindings=frame_bindings
            )
            evidence["provider"] = raw_resp.get("provider") or "unknown"
            evidence["model"] = raw_resp.get("model") or ""
            evidence["usage"] = raw_resp.get("usage") or {}
            if raw_resp.get("error"):
                evidence["degraded"] = True
                evidence["provider_error"] = raw_resp["error"]
            return evidence
        except Exception as exc:  # noqa: BLE001
            return {
                "gap_id": gap_id,
                "error": type(exc).__name__,
                "message": str(exc),
                "frame_ids": list(frame_ids),
                "observation_only": True,
                "fact_verified": False,
                "provider": "error",
            }

    def _mock_obj(
        self, *, gap_id: str, frame_ids: Sequence[str], gap_note: str
    ) -> Dict[str, Any]:
        kind = "general"
        if "goal_action" in gap_id:
            kind = "goal_action"
        elif "scoreboard" in gap_id:
            kind = "scoreboard"
        elif "reaction" in gap_id:
            kind = "reaction"
        elif "setup" in gap_id:
            kind = "setup"
        actions = {
            "goal_action": ["shot near goal", "possible goal event"],
            "scoreboard": ["scorebug visible"],
            "reaction": ["celebration or crowd reaction"],
            "setup": ["defensive crisis or conceded-goal context candidate"],
            "general": ["football match scene"],
        }[kind]
        return {
            "observed_actions": actions,
            "possible_teams": [],
            "story_relation": f"mock observation for {gap_id}; {gap_note[:80]}",
            "confidence": 0.35,
            "frame_ids": list(frame_ids),
            "notes": "mock VLM — not factual verification",
        }


def discover_vision_provider() -> Any:
    """兼容旧接口：返回状态对象。"""
    api = ApiProvider(force_mock=not False)
    st = api.status()
    return type(
        "D",
        (),
        {
            "available": st["vision_ready"],
            "kind": "openai_compatible" if st["vision_ready"] else "mock",
            "base_url": st["vision"]["base_url"],
            "model": st["vision"]["model"],
            "notes": st["notes"],
            "discovered": [],
            "to_dict": lambda self=None, _st=st: {
                "available": _st["vision_ready"],
                "kind": "openai_compatible" if _st["vision_ready"] else "mock",
                "base_url": _st["vision"]["base_url"],
                "model": _st["vision"]["model"],
                "notes": _st["notes"],
                "discovered": [],
            },
        },
    )()
