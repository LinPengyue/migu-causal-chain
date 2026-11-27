"""Phase C-1 evidence task state machine."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

TASK_STATUSES = ("open", "searching", "candidate_found", "verified", "unresolved")


def seed_tasks_from_score_analysis(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Create localization tasks from generic score-transition events (no hardcoded scores)."""
    tasks: List[Dict[str, Any]] = []
    events = analysis.get("events") or []
    # First occurrence per kind (later duplicates can be half-time re-shows).
    by_kind = {}
    for e in events:
        by_kind.setdefault(e["kind"], e)

    def _window_around(t: Optional[float], pad: float = 50.0) -> Optional[Dict[str, float]]:
        """Pad kept <=50s so candidate span <=100s fits coarse_search max (120s)."""
        if t is None:
            return None
        return {"start": max(0.0, float(t) - pad), "end": float(t) + pad}

    mapping = [
        ("locate_deficit_goal", "deficit_goal", "deficit_observed"),
        ("locate_equalizer_goal", "equalizer_goal", "equalizer_observed"),
        ("locate_go_ahead_goal", "go_ahead_goal", "go_ahead_observed"),
    ]
    for tid, need, kind in mapping:
        ev = by_kind.get(kind)
        cand = _window_around(ev.get("media_start_sec") if ev else None)
        tasks.append(
            {
                "task_id": tid,
                "narrative_need": need,
                "description": f"Locate live goal action for {need}",
                "status": "open",
                "candidate_window": cand,
                "refined_window": None,
                "linked_evidence_ids": [],
                "linked_frame_ids": [],
                "localization_grade": None,
                "expected_score_after": list(ev["score"]) if ev and ev.get("score") else None,
                "score_event": ev,
                "notes": "",
            }
        )
    tasks.append(
        {
            "task_id": "verify_final_result",
            "narrative_need": "final_or_late_scoreboard",
            "description": "Verify late/final visible scoreboard state if possible",
            "status": "open",
            "candidate_window": None,
            "refined_window": None,
            "linked_evidence_ids": [],
            "linked_frame_ids": [],
            "localization_grade": None,
            "expected_score_after": analysis.get("go_ahead_score"),
            "score_event": None,
            "notes": "",
        }
    )
    return tasks


def seed_tasks_generic_open() -> List[Dict[str, Any]]:
    return [
        {
            "task_id": tid,
            "narrative_need": need,
            "description": desc,
            "status": "open",
            "candidate_window": None,
            "refined_window": None,
            "linked_evidence_ids": [],
            "linked_frame_ids": [],
            "localization_grade": None,
            "expected_score_after": None,
            "score_event": None,
            "notes": "",
        }
        for tid, need, desc in [
            ("locate_deficit_goal", "deficit_goal", "Locate deficit-causing goal action"),
            ("locate_equalizer_goal", "equalizer_goal", "Locate equalizer goal action"),
            ("locate_go_ahead_goal", "go_ahead_goal", "Locate go-ahead goal action"),
            ("verify_final_result", "final_or_late_scoreboard", "Verify late scoreboard"),
        ]
    ]


class TaskBoard:
    def __init__(self, tasks: Optional[Sequence[Dict[str, Any]]] = None) -> None:
        self.tasks: List[Dict[str, Any]] = [dict(t) for t in (tasks or seed_tasks_generic_open())]

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        for t in self.tasks:
            if t.get("task_id") == task_id:
                return t
        return None

    def open_tasks(self) -> List[Dict[str, Any]]:
        return [t for t in self.tasks if t.get("status") in ("open", "searching", "candidate_found")]

    def update_from_grade(
        self,
        task_id: str,
        *,
        grade: str,
        evidence_id: Optional[str],
        frame_ids: Sequence[str],
        refined_window: Optional[Dict[str, float]],
        notes: str = "",
    ) -> None:
        t = self.get(task_id)
        if not t:
            return
        t["localization_grade"] = grade
        t["notes"] = notes
        if refined_window:
            t["refined_window"] = refined_window
        if evidence_id:
            ids = list(t.get("linked_evidence_ids") or [])
            if evidence_id not in ids:
                ids.append(evidence_id)
            t["linked_evidence_ids"] = ids
        fids = list(dict.fromkeys(list(t.get("linked_frame_ids") or []) + list(frame_ids)))
        t["linked_frame_ids"] = fids
        if grade == "action_corroborated":
            t["status"] = "verified"
        elif grade in ("action_localized", "goal_candidate"):
            t["status"] = "candidate_found"
        elif grade == "scoreboard_only":
            t["status"] = "candidate_found"
            t["notes"] = (t.get("notes") or "") + "|scoreboard_only_not_action"
        elif grade == "unresolved":
            if t.get("status") == "searching":
                t["status"] = "unresolved"
        if t.get("status") == "open":
            t["status"] = "searching"

    def mark_searching(self, task_id: str) -> None:
        t = self.get(task_id)
        if t and t.get("status") == "open":
            t["status"] = "searching"

    def to_json(self) -> Dict[str, Any]:
        return {
            "schema": "v2_story_evidence_tasks_phase_c1_v1",
            "tasks": self.tasks,
            "counts": {
                s: sum(1 for t in self.tasks if t.get("status") == s) for s in TASK_STATUSES
            },
            "render_ready": False,
        }
