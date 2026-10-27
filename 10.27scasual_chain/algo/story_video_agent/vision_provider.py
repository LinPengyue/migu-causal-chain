"""VLM 视觉理解（Phase 2C）：严格 frame_id 绑定；degraded/非法 JSON 不得 observed。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from story_video_agent.api_provider import ApiCallError, ApiConfigError, ApiProvider

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


class EvidenceNormalizationError(ValueError):
    """证据无法规范化为可信观察。"""


def _extract_json_obj(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise EvidenceNormalizationError("empty VLM response")
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    fence = _JSON_FENCE.search(text)
    if fence:
        try:
            obj = json.loads(fence.group(1))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError as exc:
            raise EvidenceNormalizationError("invalid JSON fence") from exc
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError as exc:
            raise EvidenceNormalizationError("invalid JSON object") from exc
    raise EvidenceNormalizationError("VLM response is not strict JSON object")


def normalize_evidence(
    raw: Dict[str, Any],
    *,
    gap_id: str,
    frame_ids: Sequence[str],
    frame_bindings: Sequence[Dict[str, Any]],
    provider_mode: str,
    model: str = "",
    raw_response_excerpt: str = "",
) -> Dict[str, Any]:
    """仅接受模型实际引用且属于本次输入的 frame_id；禁止自动填全部帧。"""
    if provider_mode == "degraded":
        raise EvidenceNormalizationError("degraded provider response cannot be observed")
    if provider_mode not in ("mock", "real", "cache"):
        raise EvidenceNormalizationError(f"unknown provider_mode {provider_mode}")

    allowed = set(frame_ids)
    raw_cited = raw.get("frame_ids")
    if raw_cited is None:
        raw_cited = raw.get("cited_frame_ids")
    if not isinstance(raw_cited, list) or not raw_cited:
        raise EvidenceNormalizationError("model did not cite any frame_ids")
    cited: List[str] = []
    invalid: List[str] = []
    for item in raw_cited:
        fid = str(item)
        if fid in allowed:
            if fid not in cited:
                cited.append(fid)
        else:
            invalid.append(fid)
    if invalid:
        raise EvidenceNormalizationError(f"invalid frame_ids cited: {invalid}")
    if not cited:
        raise EvidenceNormalizationError("no valid frame_ids after filtering")

    actions = list(raw.get("observed_actions") or raw.get("actions") or [])
    if not actions and not str(raw.get("story_relation") or "").strip():
        raise EvidenceNormalizationError("empty visual evidence (no actions/relation)")

    stripped = [
        k
        for k in raw.keys()
        if k.lower() in ("timestamp", "time", "t_sec", "media_sec", "pts", "actual_time")
    ]
    return {
        "gap_id": gap_id,
        "observed_actions": actions,
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
        "provider_mode": provider_mode,
        "provider": "mock" if provider_mode == "mock" else "openai_compatible",
        "model": model,
        "raw_response_excerpt": raw_response_excerpt[:1500],
        "normalized_ok": True,
        "observation_only": True,
        "fact_verified": False,
    }


def detect_score_conflict(
    *,
    gap_id: str,
    evidence: Dict[str, Any],
    gap: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """简单冲突：进球/记分牌任务但模型否认相关画面。"""
    actions = " ".join(str(a).lower() for a in (evidence.get("observed_actions") or []))
    relation = str(evidence.get("story_relation") or "").lower()
    notes = str(evidence.get("notes") or "").lower()
    blob = f"{actions} {relation} {notes}"
    neg = any(
        k in blob
        for k in (
            "no goal",
            "not a goal",
            "unrelated",
            "no scoreboard",
            "cannot see score",
            "irrelevant",
            "无进球",
            "无关",
            "看不见比分",
        )
    )
    kind = (gap or {}).get("kind") or ""
    if gap_id.endswith("goal_action") or kind in ("action_verify", "scoreboard"):
        if neg or float(evidence.get("confidence") or 0) < 0.15:
            return {
                "gap_id": gap_id,
                "type": "vlm_score_event_conflict",
                "detail": "VLM evidence weak/negative vs expected goal/scoreboard window",
                "confidence": evidence.get("confidence"),
            }
    return None


class VisionProvider:
    def __init__(self, api: Optional[ApiProvider] = None, *, force_mock: bool = False) -> None:
        self.api = api or ApiProvider(force_mock=force_mock)
        if force_mock:
            self.api.force_mock = True
            self.api.require_real = False

    def describe_frames(
        self,
        *,
        gap_id: str,
        gap_note: str,
        frame_paths: Sequence[Path],
        frame_ids: Sequence[str],
        frame_bindings: Sequence[Dict[str, Any]],
        gap: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        mock_obj = self._mock_obj(gap_id=gap_id, frame_ids=frame_ids, gap_note=gap_note)
        prompt = (
            "You are a sports broadcast vision assistant. "
            "Return ONE JSON object with keys: observed_actions (string[]), "
            "possible_teams (string[]), story_relation (string), confidence (0-1), "
            "frame_ids (NON-EMPTY subset of allowed ids that you actually used), notes. "
            "Cite only frame_ids you relied on; do not list unused frames. "
            "Do NOT invent timestamps. "
            f"gap_id={gap_id}. context={gap_note}. allowed_frame_ids={list(frame_ids)}."
        )
        try:
            raw_resp = self.api.vision_json(
                prompt=prompt,
                frame_paths=frame_paths,
                frame_ids=frame_ids,
                mock_obj=mock_obj,
            )
        except (ApiConfigError, ApiCallError) as exc:
            return {
                "gap_id": gap_id,
                "error": type(exc).__name__,
                "message": str(exc),
                "provider_mode": "degraded",
                "normalized_ok": False,
                "fact_verified": False,
                "observation_only": True,
                "frame_ids": [],
            }

        mode = str(raw_resp.get("provider_mode") or raw_resp.get("provider") or "")
        if mode == "openai_compatible":
            mode = "real"
        if raw_resp.get("error") or mode == "degraded":
            return {
                "gap_id": gap_id,
                "error": "degraded",
                "message": str(raw_resp.get("error") or "degraded vision response"),
                "provider_mode": "degraded",
                "normalized_ok": False,
                "fact_verified": False,
                "observation_only": True,
                "raw_response_excerpt": str(raw_resp.get("content") or "")[:800],
                "frame_ids": [],
            }

        try:
            raw = _extract_json_obj(str(raw_resp.get("content") or ""))
            evidence = normalize_evidence(
                raw,
                gap_id=gap_id,
                frame_ids=frame_ids,
                frame_bindings=frame_bindings,
                provider_mode=mode if mode in ("mock", "real", "cache") else "mock",
                model=str(raw_resp.get("model") or ""),
                raw_response_excerpt=str(
                    raw_resp.get("raw_response_excerpt") or raw_resp.get("content") or ""
                ),
            )
            evidence["usage"] = raw_resp.get("usage") or {}
            conflict = detect_score_conflict(gap_id=gap_id, evidence=evidence, gap=gap)
            if conflict:
                evidence["conflict"] = conflict
                evidence["normalized_ok"] = False
                evidence["error"] = "vlm_score_event_conflict"
                evidence["message"] = conflict["detail"]
            return evidence
        except EvidenceNormalizationError as exc:
            return {
                "gap_id": gap_id,
                "error": "EvidenceNormalizationError",
                "message": str(exc),
                "provider_mode": mode or "error",
                "normalized_ok": False,
                "fact_verified": False,
                "observation_only": True,
                "raw_response_excerpt": str(raw_resp.get("content") or "")[:800],
                "frame_ids": [],
            }

    def _mock_obj(
        self, *, gap_id: str, frame_ids: Sequence[str], gap_note: str
    ) -> Dict[str, Any]:
        # mock 也必须显式引用至少一个合法 frame_id（取第一个），禁止隐含“全部帧”
        cited = [frame_ids[0]] if frame_ids else []
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
            "frame_ids": cited,
            "notes": "mock VLM — not factual verification; not accuracy benchmark",
        }

    @property
    def stats(self) -> Any:
        usage = self.api.stats.summary()
        vision = usage.get("by_role", {}).get("vision", {})

        class _S:
            def to_dict(self_inner) -> Dict[str, Any]:
                return {
                    "calls": vision.get("real_requests", 0) + usage.get("mock_calls", 0),
                    "real_requests": vision.get("real_requests", 0),
                    "failures": usage.get("failures", 0),
                    "elapsed_sec": usage.get("elapsed_sec_real", 0.0),
                    "tokens": vision.get("tokens", 0),
                    "est_cost_usd": vision.get("est_cost_usd", 0.0),
                }

        return _S()
