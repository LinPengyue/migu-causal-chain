"""Round 2.3 Story Memory for global planner."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set


class V2R23StoryMemory:
    def __init__(self) -> None:
        self.score_path: List[Any] = []
        self.key_events: List[Dict[str, Any]] = []
        self.strip_summaries: List[Dict[str, Any]] = []
        self.selected_node_ids: List[str] = []
        self.excluded_node_ids: List[str] = []
        self.selection_reasons: Dict[str, str] = {}
        self.exclusion_reasons: Dict[str, str] = {}
        self.beat_assignments: Dict[str, List[str]] = {
            "setup": [],
            "buildup": [],
            "turning": [],
            "climax": [],
            "resolution": [],
        }
        self.relations: List[Dict[str, Any]] = []
        self.pending_video_checks: List[Dict[str, Any]] = []
        self.video_check_results: List[Dict[str, Any]] = []
        self.tool_log: List[Dict[str, Any]] = []
        self.discovery_status: str = "unresolved"
        self.story_hypothesis: str = "T01_comeback_candidate"
        self.budget: Dict[str, Any] = {}

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema": "v2_r23_story_memory_v1",
            "score_path": self.score_path,
            "n_key_events": len(self.key_events),
            "n_strip_summaries": len(self.strip_summaries),
            "selected_node_ids": list(self.selected_node_ids),
            "excluded_node_ids": list(self.excluded_node_ids),
            "selection_reasons": dict(self.selection_reasons),
            "exclusion_reasons": dict(self.exclusion_reasons),
            "beat_assignments": {k: list(v) for k, v in self.beat_assignments.items()},
            "n_relations": len(self.relations),
            "pending_video_checks": list(self.pending_video_checks),
            "n_video_checks": len(self.video_check_results),
            "discovery_status": self.discovery_status,
            "story_hypothesis": self.story_hypothesis,
            "budget": dict(self.budget),
            "tool_log": list(self.tool_log)[-40:],
            "render_ready": False,
        }

    def planner_view(self) -> Dict[str, Any]:
        """Compact state for DeepSeek (avoid dumping all 63 strips)."""
        return {
            "score_path": self.score_path,
            "story_hypothesis": self.story_hypothesis,
            "key_events": [
                {
                    "key_event_id": k.get("key_event_id"),
                    "score_before": k.get("score_before"),
                    "score_after": k.get("score_after"),
                    "media_time_sec": k.get("media_time_sec"),
                    "verification_status": k.get("verification_status"),
                    "live_or_replay": k.get("live_or_replay"),
                    "nearby_strip_ids": [s.get("strip_chain_id") for s in (k.get("nearby_strip_chains") or [])[:3]],
                }
                for k in self.key_events
            ],
            "strip_candidates": self.strip_summaries[:24],
            "selected_node_ids": self.selected_node_ids,
            "excluded_node_ids": self.excluded_node_ids[-20:],
            "beat_assignments": self.beat_assignments,
            "n_relations": len(self.relations),
            "pending_video_checks": self.pending_video_checks[:5],
            "budget": self.budget,
        }
