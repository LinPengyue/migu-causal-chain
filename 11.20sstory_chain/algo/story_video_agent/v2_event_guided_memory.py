"""Working memory for Event-Guided Story Agent Round 2."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from story_video_agent.v2_event_guided_candidate_board import CandidateBoard


class EventGuidedMemory:
    def __init__(
        self,
        *,
        duration: float,
        event_digest: Dict[str, Any],
        board: CandidateBoard,
        planner_mode: str = "agent",
    ) -> None:
        self.duration = float(duration)
        self.event_digest = event_digest
        self.board = board
        self.planner_mode = planner_mode  # agent | rule | fixed
        self.verifications: List[Dict[str, Any]] = []
        self.search_history: List[Dict[str, Any]] = []
        self.evidence_records: List[Dict[str, Any]] = []
        self.inferred_relations: List[Dict[str, Any]] = []
        self.inferred_beats: Dict[str, Any] = {}
        self.discovery_status: Optional[str] = None
        self.discovery_reason: Optional[str] = None
        self.autonomous_decisions: List[Dict[str, Any]] = []

    def add_verification(self, row: Dict[str, Any]) -> None:
        self.verifications.append(row)

    def add_search(self, row: Dict[str, Any]) -> None:
        self.search_history.append(row)

    def add_evidence(self, rec: Dict[str, Any]) -> None:
        self.evidence_records.append(rec)

    def log_autonomy(self, row: Dict[str, Any]) -> None:
        self.autonomous_decisions.append(row)

    def facts_for_planner(self, *, remaining: int) -> Dict[str, Any]:
        return {
            "duration_sec": self.duration,
            "remaining_steps": remaining,
            "planner_mode": self.planner_mode,
            "input_source": self.event_digest.get("input_source"),
            "team_names": self.event_digest.get("team_names"),
            "score_anchors": self.board.list_anchors(),
            "open_candidates": self.board.list_candidates(status="open")[:20],
            "selected_candidates": self.board.list_candidates(status="selected")[:10],
            "observing_candidates": self.board.list_candidates(status="observing")[:10],
            "localized_candidates": self.board.list_candidates(status="localized"),
            "rejected_tail": self.board.list_candidates(status="rejected")[-5:],
            "verifications_tail": self.verifications[-6:],
            "evidence_tail": self.evidence_records[-6:],
            "n_verifications": len(self.verifications),
            "search_history_tail": self.search_history[-8:],
            "rules": [
                "Select candidates from the board; do not invent event_ids",
                "Score_Recognition time ≠ proven live goal action — search earlier if needed",
                "action_localized requires frame-cited shot AND net evidence",
                "causal relations need supporting_evidence_ids; score order alone is not causal",
                "If a window is wrong, shift_search or reject — do not keep shrinking the same wrong span",
            ],
        }

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema": "v2_event_guided_memory_v2",
            "duration_sec": self.duration,
            "planner_mode": self.planner_mode,
            "input_source": self.event_digest.get("input_source"),
            "board": self.board.snapshot(),
            "verifications": self.verifications,
            "evidence_records": self.evidence_records,
            "search_history": self.search_history,
            "autonomous_decisions": self.autonomous_decisions,
            "inferred_beats": self.inferred_beats,
            "inferred_relations": self.inferred_relations,
            "discovery_status": self.discovery_status,
            "discovery_reason": self.discovery_reason,
        }
