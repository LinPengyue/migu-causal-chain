"""观察记忆：区分 sampled / observed / verified / unresolved。"""

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
    """Structured observations + per-gap evidence stage ledger."""

    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []
        self.gap_stages: Dict[str, str] = {}
        self.visual_evidence: List[Dict[str, Any]] = []

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
            # 不允许从 verified 退回 observed；允许 pending→sampled→observed
            if prev == "verified":
                return
        # VLM 描述成功不得升到 verified
        if stage == "verified":
            raise ValueError("Memory refuses verified: Phase 2B observation != fact verification")
        self.gap_stages[gap_id] = stage

    def mark_sampled(self, gap_id: str) -> None:
        self.set_stage(gap_id, "sampled")

    def mark_observed(self, gap_id: str, evidence: Dict[str, Any]) -> None:
        self.set_stage(gap_id, "observed")
        self.visual_evidence.append(dict(evidence))

    def mark_unresolved(self, gap_id: str, reason: str = "") -> None:
        self.set_stage(gap_id, "unresolved", force=True)
        if reason:
            self.items.append(
                {
                    "tool": None,
                    "arguments": {"gap_id": gap_id},
                    "observation": {"stage": "unresolved", "reason": reason},
                }
            )

    def snapshot(self) -> Dict[str, Any]:
        return {
            "items": self.items,
            "gap_stages": dict(self.gap_stages),
            "visual_evidence": list(self.visual_evidence),
        }
