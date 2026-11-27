"""Round 2.4 Story Memory — observation feedback visible to DeepSeek."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from story_video_agent.v2_strip_guided_r2_3_memory import V2R23StoryMemory


class V2R24StoryMemory(V2R23StoryMemory):
    def __init__(self) -> None:
        super().__init__()
        self.strip_observations: Dict[str, Dict[str, Any]] = {}
        self.selection_change_log: List[Dict[str, Any]] = []
        self.narrative_conflicts: List[Dict[str, Any]] = []
        self.playout_policy: str = "prefer_match_timeline"  # or planner_narrative
        self.r23_selected_baseline: List[str] = []

    def record_observation(self, obs: Dict[str, Any]) -> None:
        nid = str(obs.get("node_id") or "")
        if not nid:
            return
        self.strip_observations[nid] = obs
        self.video_check_results.append(obs)

    def unselect_node(self, node_id: str, *, why: str, evidence_id: Optional[str] = None) -> None:
        if node_id in self.selected_node_ids:
            self.selected_node_ids = [x for x in self.selected_node_ids if x != node_id]
            for beat, members in self.beat_assignments.items():
                self.beat_assignments[beat] = [x for x in members if x != node_id]
            self.selection_reasons.pop(node_id, None)
        if node_id not in self.excluded_node_ids:
            self.excluded_node_ids.append(node_id)
        self.exclusion_reasons[node_id] = why
        self.selection_change_log.append(
            {
                "action": "unselect",
                "node_id": node_id,
                "why": why,
                "evidence_id": evidence_id,
            }
        )

    def snapshot(self) -> Dict[str, Any]:
        snap = super().snapshot()
        snap["schema"] = "v2_r24_story_memory_v1"
        snap["strip_observations"] = dict(self.strip_observations)
        snap["selection_change_log"] = list(self.selection_change_log)
        snap["narrative_conflicts"] = list(self.narrative_conflicts)
        snap["playout_policy"] = self.playout_policy
        snap["r23_selected_baseline"] = list(self.r23_selected_baseline)
        return snap

    def planner_view(self) -> Dict[str, Any]:
        view = super().planner_view()
        # Critical R2.4: feed observations back into DeepSeek state
        recent_obs = []
        for nid, obs in list(self.strip_observations.items())[-12:]:
            recent_obs.append(
                {
                    "node_id": nid,
                    "recommendation": obs.get("recommendation"),
                    "supports_prior_why": obs.get("supports_prior_why"),
                    "live_or_replay": obs.get("live_or_replay"),
                    "matches_predicted_events": obs.get("matches_predicted_events"),
                    "narrative_value": obs.get("narrative_value"),
                    "suggested_beat": obs.get("suggested_beat"),
                    "duplicate_of": obs.get("duplicate_of"),
                    "summary": obs.get("summary") or obs.get("notes"),
                    "observed_actions": (obs.get("observed_actions") or [])[:6],
                    "evidence_id": obs.get("evidence_id"),
                    "verification_status": obs.get("verification_status") or "observed_not_verified_causal",
                }
            )
        view["strip_observations"] = recent_obs
        view["pending_observation_reviews"] = [
            nid
            for nid in self.selected_node_ids
            if nid.startswith("strip_") and nid not in self.strip_observations
        ]
        view["selection_change_log"] = self.selection_change_log[-12:]
        view["narrative_conflicts"] = self.narrative_conflicts[-8:]
        view["playout_policy"] = self.playout_policy
        view["instruction_hint"] = (
            "If an observation recommendation is drop/replace, call unselect_node then optionally "
            "select a different strip. Do not finish while pending_observation_reviews is non-empty "
            "unless budget is exhausted. Never upgrade predicted strips to verified_action."
        )
        return view
