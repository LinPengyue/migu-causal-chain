"""Queryable candidate index for Event-Guided DeepSeek search."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from story_video_agent.v2_event_adapter import (
    candidate_events_near_anchors,
    score_transition_anchors,
)


class CandidateBoard:
    """Stateful board: DeepSeek selects / rejects / localizes candidates."""

    def __init__(
        self,
        events: Sequence[Dict[str, Any]],
        *,
        pad_sec: float = 90.0,
    ) -> None:
        self.anchors = score_transition_anchors(events)
        raw = candidate_events_near_anchors(events, self.anchors, pad_sec=pad_sec)
        # Also seed one synthetic "search slot" per score_change / initial for open search
        self.candidates: Dict[str, Dict[str, Any]] = {}
        for row in raw:
            e = row["event"]
            eid = e["event_id"]
            self.candidates[eid] = {
                "candidate_event_id": eid,
                "event_type": e.get("event_type"),
                "event_time_sec": e.get("event_time_sec"),
                "media_start_sec": e.get("media_start_sec"),
                "media_end_sec": e.get("media_end_sec"),
                "scoreboard": e.get("scoreboard"),
                "score_pair": e.get("score_pair"),
                "is_replay": e.get("is_replay"),
                "broadcast_phase": e.get("broadcast_phase"),
                "anchor": row.get("anchor"),
                "status": "open",  # open|selected|observing|rejected|localized|abandoned
                "credibility": 0.4,
                "observations": [],
                "localized_media_in": None,
                "localized_media_out": None,
                "verification_status": "unresolved",
                "evidence_record": None,
                "search_center_sec": e.get("event_time_sec"),
                "reject_reasons": [],
                "search_attempts": 0,
            }
        # For each score change / initial deficit, add an early-search probe:
        # Score_Recognition can lag live goals by 1–3 minutes.
        for i, a in enumerate(self.anchors):
            if a.get("kind") not in ("score_change", "initial_score"):
                continue
            t = float(a.get("event_time_sec") or 0)
            for lag_name, lag in (("early150", 150.0), ("early90", 90.0)):
                aid = f"virtual_{lag_name}_{i}_{a.get('event_id')}"
                if aid in self.candidates:
                    continue
                self.candidates[aid] = {
                    "candidate_event_id": aid,
                    "event_type": "score_lag_probe",
                    "event_time_sec": max(0.0, t - lag),
                    "media_start_sec": max(0.0, t - lag - 5.0),
                    "media_end_sec": max(0.0, t - lag + 5.0),
                    "scoreboard": None,
                    "score_pair": a.get("score_after") or a.get("score_pair"),
                    "is_replay": False,
                    "broadcast_phase": "LIVE",
                    "anchor": {
                        "score_before": a.get("score_before"),
                        "score_after": a.get("score_after") or a.get("score_pair"),
                        "anchor_event_id": a.get("event_id"),
                        "anchor_time_sec": a.get("event_time_sec"),
                        "probe_lag_sec": lag,
                    },
                    "status": "open",
                    "credibility": 0.45 if lag == 150.0 else 0.4,
                    "observations": [],
                    "localized_media_in": None,
                    "localized_media_out": None,
                    "verification_status": "unresolved",
                    "evidence_record": None,
                    "search_center_sec": max(0.0, t - lag),
                    "reject_reasons": [],
                    "search_attempts": 0,
                    "virtual": True,
                }

    def list_anchors(self) -> List[Dict[str, Any]]:
        return list(self.anchors)

    def list_candidates(self, *, status: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = []
        for c in self.candidates.values():
            if status and c["status"] != status:
                continue
            rows.append(
                {
                    "candidate_event_id": c["candidate_event_id"],
                    "event_type": c["event_type"],
                    "event_time_sec": c["event_time_sec"],
                    "score_pair": c["score_pair"],
                    "is_replay": c["is_replay"],
                    "status": c["status"],
                    "credibility": c["credibility"],
                    "search_center_sec": c["search_center_sec"],
                    "verification_status": c["verification_status"],
                    "anchor": c.get("anchor"),
                    "n_observations": len(c["observations"]),
                    "search_attempts": int(c.get("search_attempts") or 0),
                    "pending_observe_after_shift": bool(c.get("pending_observe_after_shift")),
                    "virtual": bool(c.get("virtual")),
                }
            )
        rows.sort(key=lambda r: float(r.get("event_time_sec") or 0))
        return rows

    def get(self, event_id: str) -> Optional[Dict[str, Any]]:
        return self.candidates.get(event_id)

    def select(self, event_id: str) -> Dict[str, Any]:
        c = self.candidates.get(event_id)
        if not c:
            return {"ok": False, "error": f"unknown candidate {event_id}"}
        c["status"] = "selected"
        return {"ok": True, "candidate": self._public(c)}

    def reject(self, event_id: str, reason: str) -> Dict[str, Any]:
        c = self.candidates.get(event_id)
        if not c:
            return {"ok": False, "error": f"unknown candidate {event_id}"}
        c["status"] = "rejected"
        c["credibility"] = min(c["credibility"], 0.15)
        c["reject_reasons"].append(reason)
        c["verification_status"] = "rejected"
        return {"ok": True, "candidate": self._public(c)}

    def shift_search(self, event_id: str, delta_sec: float) -> Dict[str, Any]:
        c = self.candidates.get(event_id)
        if not c:
            return {"ok": False, "error": f"unknown candidate {event_id}"}
        center = float(c.get("search_center_sec") or c.get("event_time_sec") or 0)
        c["search_center_sec"] = max(0.0, center + float(delta_sec))
        c["status"] = "observing"
        c["search_attempts"] = int(c.get("search_attempts") or 0) + 1
        c["pending_observe_after_shift"] = True
        return {
            "ok": True,
            "candidate_event_id": event_id,
            "search_center_sec": c["search_center_sec"],
            "suggested_window": {
                "start": max(0.0, c["search_center_sec"] - 5.0),
                "end": c["search_center_sec"] + 5.0,
            },
        }

    def add_observation(
        self, event_id: str, obs_summary: Dict[str, Any], evidence: Dict[str, Any]
    ) -> Dict[str, Any]:
        c = self.candidates.get(event_id)
        if not c:
            return {"ok": False, "error": f"unknown candidate {event_id}"}
        c["status"] = "observing"
        c["observations"].append(obs_summary)
        c["search_attempts"] = int(c.get("search_attempts") or 0) + 1
        c["pending_observe_after_shift"] = False
        # Update credibility from evidence
        if evidence.get("grade") == "action_localized":
            c["credibility"] = min(0.95, c["credibility"] + 0.35)
        elif evidence.get("grade") == "goal_candidate":
            c["credibility"] = min(0.8, c["credibility"] + 0.15)
        elif evidence.get("grade") == "scoreboard_only":
            c["credibility"] = max(0.1, c["credibility"] - 0.05)
        else:
            c["credibility"] = max(0.05, c["credibility"] - 0.1)
        if evidence.get("live_or_replay") == "replay":
            c["credibility"] = max(0.05, c["credibility"] - 0.15)
        c["verification_status"] = evidence.get("verification_status") or c["verification_status"]
        return {"ok": True, "credibility": c["credibility"], "status": c["status"]}

    def confirm_localization(
        self,
        event_id: str,
        *,
        media_in: float,
        media_out: float,
        evidence_record: Dict[str, Any],
    ) -> Dict[str, Any]:
        c = self.candidates.get(event_id)
        if not c:
            return {"ok": False, "error": f"unknown candidate {event_id}"}
        c["localized_media_in"] = float(media_in)
        c["localized_media_out"] = float(media_out)
        c["evidence_record"] = evidence_record
        c["status"] = "localized"
        c["verification_status"] = evidence_record.get("verification_status") or "localized"
        c["credibility"] = max(c["credibility"], 0.7)
        return {"ok": True, "candidate": self._public(c)}

    def localized(self) -> List[Dict[str, Any]]:
        return [self._public(c) for c in self.candidates.values() if c["status"] == "localized"]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema": "v2_candidate_board_v1",
            "anchors": self.anchors,
            "candidates": [self._public(c) for c in self.candidates.values()],
        }

    @staticmethod
    def _public(c: Dict[str, Any]) -> Dict[str, Any]:
        return {
            k: c.get(k)
            for k in (
                "candidate_event_id",
                "event_type",
                "event_time_sec",
                "media_start_sec",
                "media_end_sec",
                "score_pair",
                "is_replay",
                "anchor",
                "status",
                "credibility",
                "search_center_sec",
                "localized_media_in",
                "localized_media_out",
                "verification_status",
                "evidence_record",
                "reject_reasons",
                "n_observations",
                "search_attempts",
                "pending_observe_after_shift",
                "virtual",
            )
            if k != "n_observations"
        } | {"n_observations": len(c.get("observations") or [])}
