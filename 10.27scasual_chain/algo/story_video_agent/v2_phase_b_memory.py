"""Phase B story discovery memory: evidence items, tasks, coverage."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from story_video_agent.v2_coverage import SearchCoverage
from story_video_agent.v2_evidence_schema import (
    count_by_status,
    dedupe_evidence_items,
    items_from_observation,
)


class V2PhaseBMemory:
    def __init__(self, *, duration_sec: float, partition_sec: float = 600.0) -> None:
        self.duration_sec = float(duration_sec)
        self.hypotheses: List[Dict[str, Any]] = []
        self.discovery_status: str = "searching"  # story_candidate|partial_story|no_comeback|unresolved|searching
        self.evidence_items: List[Dict[str, Any]] = []
        self.evidence_tasks: List[Dict[str, Any]] = []
        self.observations: List[Dict[str, Any]] = []
        self.conflicts: List[Dict[str, Any]] = []
        self.unresolved: List[Dict[str, Any]] = []
        self.search_history: List[Dict[str, Any]] = []
        self.coverage = SearchCoverage(duration_sec=duration_sec, partition_sec=partition_sec)
        self._seed_default_tasks()

    def _seed_default_tasks(self) -> None:
        """Open evidence tasks for T01-type discovery — not asserting the match is a comeback."""
        for tid, role, need in [
            ("task_deficit", "deficit_score_change", "Find if/when one side fell behind"),
            ("task_equalizer", "equalizer", "Find if/when score was leveled"),
            ("task_go_ahead", "go_ahead", "Find if/when a side took the lead after trailing"),
            ("task_result", "result_state", "Find credible late/final scoreboard state if visible"),
        ]:
            self.evidence_tasks.append(
                {
                    "task_id": tid,
                    "narrative_need": role,
                    "description": need,
                    "status": "open",
                    "linked_evidence_ids": [],
                    "notes": "",
                }
            )

    def add_tool_result(self, decision: Dict[str, Any], observation: Dict[str, Any]) -> None:
        tool = str(decision.get("tool") or "")
        ok = "error" not in observation
        self.search_history.append(
            {
                "tool": tool,
                "arguments": decision.get("arguments") or {},
                "ok": ok,
                "layer": observation.get("layer"),
            }
        )
        frames = observation.get("frames") or []
        sampled = observation.get("sampled_media_times") or [
            f.get("requested_media_sec") for f in frames if isinstance(f, dict)
        ]
        perc = observation.get("perception") or {}
        self.coverage.add(
            tool=tool,
            requested_start=observation.get("media_start_sec"),
            requested_end=observation.get("media_end_sec"),
            sampled_times=[t for t in sampled if t is not None],
            observed=ok and bool(perc.get("normalized_ok")),
            failed=not ok or bool(observation.get("error")),
            frame_ids=list(perc.get("frame_ids") or []),
            error=str(observation.get("error") or "") or None,
        )
        row = {
            "tool": tool,
            "layer": observation.get("layer"),
            "media_start_sec": observation.get("media_start_sec"),
            "media_end_sec": observation.get("media_end_sec"),
            "sampled_media_times": list(sampled or []),
            "frame_ids": list(perc.get("frame_ids") or []),
            "observed_actions": list(perc.get("observed_actions") or []),
            "confidence": perc.get("confidence"),
            "provider_mode": perc.get("provider_mode"),
            "notes": perc.get("notes"),
            "fact_verified": False,
            "status": "observed" if perc.get("normalized_ok") else "unresolved",
        }
        if observation.get("error"):
            row["status"] = "failed"
            row["error"] = observation.get("error")
            row["message"] = observation.get("message")
            self.unresolved.append(row)
        self.observations.append(row)
        new_items = items_from_observation(observation, tool=tool)
        self.evidence_items.extend(new_items)
        self.evidence_items = dedupe_evidence_items(self.evidence_items)

    def set_hypothesis(self, hyp: Dict[str, Any]) -> None:
        self.hypotheses.append(dict(hyp))
        status = str(hyp.get("discovery_status") or hyp.get("status") or "")
        if status in ("story_candidate", "partial_story", "no_comeback", "unresolved"):
            self.discovery_status = status

    def update_task(self, task_id: str, **fields: Any) -> None:
        for t in self.evidence_tasks:
            if t.get("task_id") == task_id:
                t.update(fields)
                return

    def planner_facts(self, *, limit: int = 8) -> Dict[str, Any]:
        cov = self.coverage.summary()
        untouched = [p for p in cov["partitions"] if p["status"] == "untouched"][:8]
        return {
            "discovery_status": self.discovery_status,
            "hypotheses": self.hypotheses[-2:],
            "evidence_items_deduped": self.evidence_items[-limit:],
            "evidence_status_counts": count_by_status(self.evidence_items),
            "evidence_tasks": self.evidence_tasks,
            "recent_observations": [
                {
                    "tool": o.get("tool"),
                    "layer": o.get("layer"),
                    "media_start_sec": o.get("media_start_sec"),
                    "media_end_sec": o.get("media_end_sec"),
                    "n_sampled": len(o.get("sampled_media_times") or []),
                    "status": o.get("status"),
                    "actions_head": (o.get("observed_actions") or [])[:3],
                    "notes_head": str(o.get("notes") or "")[:240],
                }
                for o in self.observations[-limit:]
            ],
            "coverage_summary": {
                "fraction_partitions_with_observation": cov["fraction_partitions_with_observation"],
                "partitions_untouched": cov["partitions_untouched"],
                "partitions_observed": cov["partitions_observed"],
                "disclaimer": cov["disclaimer"],
            },
            "untouched_partitions_sample": untouched,
            "n_observations": len(self.observations),
            "n_evidence_items": len(self.evidence_items),
            "search_history_tail": self.search_history[-12:],
        }

    def to_story_evidence(self, *, video: str, stop_reason: str, budget: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "schema": "v2_story_evidence_phase_b_v1",
            "video": video,
            "story_type_target": "T01_comeback",
            "discovery_status": self.discovery_status,
            "hypotheses": self.hypotheses,
            "evidence_items": self.evidence_items,
            "evidence_status_counts": count_by_status(self.evidence_items),
            "video_evidence": self.observations,
            "conflicts": self.conflicts,
            "unresolved": self.unresolved,
            "search_history": self.search_history,
            "stop_reason": stop_reason,
            "budget": budget,
            "semantic_verified": False,
            "render_ready": False,
            "notes": [
                "candidate_events replaced by deduped evidence_items",
                "Sparse samples are not full-interval observation",
                "No events.json/causal.json used as inference input",
            ],
        }

    def to_story_discovery(self, *, video: str, stop_reason: str) -> Dict[str, Any]:
        return {
            "schema": "v2_story_discovery_phase_b_v1",
            "video": video,
            "story_type_target": "T01_comeback",
            "discovery_status": self.discovery_status,
            "hypotheses": self.hypotheses,
            "open_tasks": [t for t in self.evidence_tasks if t.get("status") == "open"],
            "closed_tasks": [t for t in self.evidence_tasks if t.get("status") != "open"],
            "stop_reason": stop_reason,
            "render_ready": False,
            "caveat": (
                "Absence of comeback in sparse samples does not prove no_comeback "
                "unless coverage and scoreboard evidence are sufficient."
            ),
        }

    def to_evidence_tasks(self) -> Dict[str, Any]:
        return {
            "schema": "v2_story_evidence_tasks_phase_b_v1",
            "tasks": self.evidence_tasks,
            "render_ready": False,
        }
