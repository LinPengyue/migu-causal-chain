"""V2 Phase A evidence memory: hypotheses, candidates, conflicts, search history."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class V2StoryMemory:
    def __init__(self) -> None:
        self.hypotheses: List[Dict[str, Any]] = []
        self.candidate_events: List[Dict[str, Any]] = []
        self.observations: List[Dict[str, Any]] = []
        self.conflicts: List[Dict[str, Any]] = []
        self.unresolved: List[Dict[str, Any]] = []
        self.checked_intervals: List[Dict[str, float]] = []
        self.search_history: List[Dict[str, Any]] = []

    def add_tool_result(self, decision: Dict[str, Any], observation: Dict[str, Any]) -> None:
        self.search_history.append(
            {
                "tool": decision.get("tool"),
                "arguments": decision.get("arguments") or {},
                "ok": "error" not in observation,
            }
        )
        if observation.get("media_start_sec") is not None:
            self.checked_intervals.append(
                {
                    "start": float(observation["media_start_sec"]),
                    "end": float(observation["media_end_sec"]),
                }
            )
        perc = observation.get("perception") or {}
        row = {
            "tool": decision.get("tool"),
            "media_start_sec": observation.get("media_start_sec"),
            "media_end_sec": observation.get("media_end_sec"),
            "frame_ids": list((perc.get("frame_ids") or [])),
            "observed_actions": list(perc.get("observed_actions") or []),
            "story_relation": perc.get("story_relation"),
            "confidence": perc.get("confidence"),
            "provider_mode": perc.get("provider_mode"),
            "notes": perc.get("notes"),
            "fact_verified": False,
            "status": "observed" if perc.get("normalized_ok") else "unresolved",
        }
        if observation.get("error"):
            row["status"] = "unresolved"
            row["error"] = observation.get("error")
            row["message"] = observation.get("message")
            self.unresolved.append(row)
        self.observations.append(row)
        # lightweight candidate extraction from actions text
        for act in row.get("observed_actions") or []:
            text = str(act).lower()
            role = "unknown"
            if "score" in text or "scoreboard" in text or "比分" in text:
                role = "scoreboard"
            elif "goal" in text or "进球" in text or "net" in text:
                role = "possible_goal"
            elif "replay" in text or "回放" in text:
                role = "replay_candidate"
            elif "celebrat" in text or "庆祝" in text:
                role = "celebration"
            self.candidate_events.append(
                {
                    "role": role,
                    "raw": act,
                    "media_start_sec": row.get("media_start_sec"),
                    "media_end_sec": row.get("media_end_sec"),
                    "frame_ids": row.get("frame_ids"),
                    "verified": False,
                    "source_tool": decision.get("tool"),
                }
            )

    def set_hypothesis(self, hyp: Dict[str, Any]) -> None:
        self.hypotheses.append(dict(hyp))

    def add_conflict(self, conflict: Dict[str, Any]) -> None:
        self.conflicts.append(dict(conflict))

    def planner_facts(self, *, limit: int = 10) -> Dict[str, Any]:
        return {
            "hypotheses": self.hypotheses[-3:],
            "recent_observations": self.observations[-limit:],
            "candidate_events": self.candidate_events[-limit:],
            "conflicts": self.conflicts[-limit:],
            "unresolved": self.unresolved[-limit:],
            "checked_intervals": self.checked_intervals[-12:],
            "n_observations": len(self.observations),
            "n_candidates": len(self.candidate_events),
        }

    def to_story_evidence(
        self,
        *,
        video: str,
        stop_reason: str,
        budget: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "schema": "v2_story_evidence_phase_a_v1",
            "video": video,
            "story_type_hypothesis": "T01_comeback",
            "hypotheses": self.hypotheses,
            "candidate_events": self.candidate_events,
            "video_evidence": self.observations,
            "conflicts": self.conflicts,
            "unresolved": self.unresolved,
            "search_history": self.search_history,
            "checked_intervals": self.checked_intervals,
            "stop_reason": stop_reason,
            "budget": budget,
            "semantic_verified": False,
            "render_ready": False,
            "notes": [
                "Phase A prototype: observations are not fact-verified goals",
                "No events.json/causal.json used as inference input",
            ],
        }
