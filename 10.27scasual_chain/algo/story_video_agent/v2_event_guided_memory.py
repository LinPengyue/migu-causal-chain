"""Working memory for Event-Guided Story Agent (no causal.json)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class EventGuidedMemory:
    def __init__(self, *, duration: float, event_digest: Dict[str, Any]) -> None:
        self.duration = float(duration)
        self.event_digest = event_digest
        self.verifications: List[Dict[str, Any]] = []
        self.search_history: List[Dict[str, Any]] = []
        self.inferred_relations: List[Dict[str, Any]] = []
        self.inferred_beats: Dict[str, Any] = {}
        self.discovery_status: Optional[str] = None
        self.discovery_reason: Optional[str] = None

    def add_verification(self, row: Dict[str, Any]) -> None:
        self.verifications.append(row)

    def add_search(self, row: Dict[str, Any]) -> None:
        self.search_history.append(row)

    def facts_for_planner(self, *, remaining: int) -> Dict[str, Any]:
        return {
            "duration_sec": self.duration,
            "remaining_steps": remaining,
            "input_source": self.event_digest.get("input_source"),
            "team_names": self.event_digest.get("team_names"),
            "score_anchors": self.event_digest.get("score_anchors"),
            "n_events_in_digest": len(self.event_digest.get("events") or []),
            "events_tail": (self.event_digest.get("events") or [])[-20:],
            "verifications_tail": self.verifications[-8:],
            "n_verifications": len(self.verifications),
            "search_history_tail": self.search_history[-6:],
            "inferred_beats": self.inferred_beats or None,
            "discovery_status": self.discovery_status,
            "rules": self.event_digest.get("rules"),
        }

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema": "v2_event_guided_memory_v1",
            "duration_sec": self.duration,
            "input_source": self.event_digest.get("input_source"),
            "score_anchors": self.event_digest.get("score_anchors"),
            "verifications": self.verifications,
            "search_history": self.search_history,
            "inferred_beats": self.inferred_beats,
            "inferred_relations": self.inferred_relations,
            "discovery_status": self.discovery_status,
            "discovery_reason": self.discovery_reason,
        }
