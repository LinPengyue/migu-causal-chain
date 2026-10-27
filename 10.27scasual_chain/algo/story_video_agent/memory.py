"""观察记忆（Phase 2C）：sampled/observed/unresolved + 冲突/已查区间/疑点。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


_STAGE_RANK = {
    "pending": 0,
    "sampled": 1,
    "observed": 2,
    "verified": 3,
    "unresolved": 4,
    "failed": 5,
    "running": 0,
}


class Memory:
    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []
        self.gap_stages: Dict[str, str] = {}
        self.visual_evidence: List[Dict[str, Any]] = []
        self.checked_intervals: Dict[str, List[Dict[str, float]]] = {}
        self.conflicts: List[Dict[str, Any]] = []
        self.unresolved_doubts: List[Dict[str, Any]] = []
        self.raw_vlm_responses: List[Dict[str, Any]] = []

    def add(self, decision: Dict[str, Any], observation: Any) -> None:
        self.items.append(
            {
                "tool": decision.get("tool"),
                "arguments": decision.get("arguments", {}),
                "observation": observation,
            }
        )

    def set_stage(self, gap_id: str, stage: str, *, force: bool = False) -> None:
        if stage not in _STAGE_RANK:
            raise ValueError(f"unknown stage {stage}")
        prev = self.gap_stages.get(gap_id)
        if (
            not force
            and prev is not None
            and _STAGE_RANK[stage] < _STAGE_RANK[prev]
            and prev not in ("unresolved", "failed")
        ):
            if prev == "verified":
                return
        if stage == "verified":
            raise ValueError("Memory refuses verified: observation != fact verification")
        self.gap_stages[gap_id] = stage

    def mark_sampled(self, gap_id: str) -> None:
        self.set_stage(gap_id, "sampled")

    def mark_observed(self, gap_id: str, evidence: Dict[str, Any]) -> None:
        if not evidence.get("normalized_ok"):
            raise ValueError("refuse observed without normalized_ok evidence")
        self.set_stage(gap_id, "observed")
        self.visual_evidence.append(dict(evidence))

    def mark_unresolved(self, gap_id: str, reason: str = "", *, doubt: Optional[Dict[str, Any]] = None) -> None:
        self.set_stage(gap_id, "unresolved", force=True)
        row = {"gap_id": gap_id, "reason": reason}
        if doubt:
            row.update(doubt)
        self.unresolved_doubts.append(row)
        if reason:
            self.items.append(
                {
                    "tool": None,
                    "arguments": {"gap_id": gap_id},
                    "observation": {"stage": "unresolved", "reason": reason},
                }
            )

    def add_checked_interval(self, gap_id: str, start: float, end: float) -> None:
        self.checked_intervals.setdefault(gap_id, []).append(
            {"start": float(start), "end": float(end)}
        )

    def add_conflict(self, conflict: Dict[str, Any]) -> None:
        self.conflicts.append(dict(conflict))

    def add_raw_vlm(self, gap_id: str, raw_excerpt: str, normalized: Dict[str, Any]) -> None:
        self.raw_vlm_responses.append(
            {
                "gap_id": gap_id,
                "raw_response_excerpt": (raw_excerpt or "")[:1500],
                "normalized_ok": bool(normalized.get("normalized_ok")),
                "provider_mode": normalized.get("provider_mode"),
                "cited_frame_ids": list(normalized.get("frame_ids") or []),
            }
        )

    def planner_facts(self, *, limit: int = 8) -> Dict[str, Any]:
        """供 Planner 的结构化事实，而非仅 count。"""
        recent = self.visual_evidence[-limit:]
        return {
            "recent_observations": [
                {
                    "gap_id": e.get("gap_id"),
                    "observed_actions": e.get("observed_actions"),
                    "story_relation": e.get("story_relation"),
                    "confidence": e.get("confidence"),
                    "frame_ids": e.get("frame_ids"),
                    "provider_mode": e.get("provider_mode"),
                    "conflict": e.get("conflict"),
                }
                for e in recent
            ],
            "gap_stages": dict(self.gap_stages),
            "unresolved_doubts": list(self.unresolved_doubts[-limit:]),
            "conflicts": list(self.conflicts[-limit:]),
            "checked_intervals": {
                k: v[-6:] for k, v in self.checked_intervals.items()
            },
            "visual_evidence_count": len(self.visual_evidence),
        }

    def snapshot(self) -> Dict[str, Any]:
        return {
            "items": self.items,
            "gap_stages": dict(self.gap_stages),
            "visual_evidence": list(self.visual_evidence),
            "checked_intervals": dict(self.checked_intervals),
            "conflicts": list(self.conflicts),
            "unresolved_doubts": list(self.unresolved_doubts),
            "raw_vlm_responses": list(self.raw_vlm_responses),
        }
