"""Memory for Strip-Guided Story Agent."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class StripGuidedMemory:
    def __init__(
        self,
        *,
        duration: float,
        strip_digest: Dict[str, Any],
        event_digest: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.duration = float(duration)
        self.strip_digest = strip_digest
        self.event_digest = event_digest or {}
        self.chain_states: Dict[str, Dict[str, Any]] = {
            c["strip_chain_id"]: {
                **c,
                "status": "open",
                "verifications": [],
                "refined_media_in": None,
                "refined_media_out": None,
                "evidence": None,
            }
            for c in (strip_digest.get("chains") or [])
        }
        self.verifications: List[Dict[str, Any]] = []
        self.decisions: List[Dict[str, Any]] = []
        self.story_candidates: List[Dict[str, Any]] = []
        self.beats: Dict[str, Any] = {}
        self.relations: List[Dict[str, Any]] = []
        self.localized_clips: List[Dict[str, Any]] = []
        self.discovery_status: Optional[str] = None
        self.discovery_reason: Optional[str] = None

    def facts_for_planner(self, *, remaining: int) -> Dict[str, Any]:
        open_c = [c for c in self.chain_states.values() if c["status"] in ("open", "selected", "observing")]
        verified = [c for c in self.chain_states.values() if c["status"] == "verified"]
        rejected = [c for c in self.chain_states.values() if c["status"] == "rejected"]
        return {
            "duration_sec": self.duration,
            "remaining_steps": remaining,
            "score_anchors": self.event_digest.get("score_anchors"),
            "team_names": self.event_digest.get("team_names"),
            "strip_rules": self.strip_digest.get("rules"),
            "n_strips": self.strip_digest.get("n_chains_total"),
            "category_counts": self.strip_digest.get("category_counts"),
            "open_strips": [
                {
                    "strip_chain_id": c["strip_chain_id"],
                    "t0_sec": c.get("t0_sec"),
                    "t1_sec": c.get("t1_sec"),
                    "predicted_category": c.get("predicted_category"),
                    "predicted_label": c.get("predicted_label"),
                    "confidence": c.get("confidence"),
                    "status": c.get("status"),
                }
                for c in open_c[:25]
            ],
            "verified_strips": [
                {
                    "strip_chain_id": c["strip_chain_id"],
                    "refined_media_in": c.get("refined_media_in"),
                    "refined_media_out": c.get("refined_media_out"),
                    "verification_status": (c.get("evidence") or {}).get("verification_status"),
                }
                for c in verified
            ],
            "rejected_tail": [
                {"strip_chain_id": c["strip_chain_id"], "reason": c.get("reject_reason")}
                for c in rejected[-5:]
            ],
            "verifications_tail": self.verifications[-6:],
            "rules": [
                "Select strips to verify; do not invent strip_chain_ids",
                "Predicted labels are hypotheses — confirm live shot/net in video",
                "Inter-chain causal requires evidence; temporal/narrative are weaker claims",
                "If strip window is wrong, refine observe_window within/near [t0,t1]",
            ],
        }

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema": "v2_strip_guided_memory_v1",
            "duration_sec": self.duration,
            "discovery_status": self.discovery_status,
            "discovery_reason": self.discovery_reason,
            "chain_states": self.chain_states,
            "verifications": self.verifications,
            "decisions": self.decisions,
            "story_candidates": self.story_candidates,
            "beats": self.beats,
            "relations": self.relations,
            "localized_clips": self.localized_clips,
            "render_ready": False,
        }
