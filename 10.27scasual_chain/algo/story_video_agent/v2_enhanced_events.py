"""Enhanced events: original events.json + video-verified inferred Goals.

Never overwrites the original file. Inferred events are source=video_agent_inferred.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


def make_inferred_goal_event(
    *,
    inferred_event_id: str,
    media_time_sec: float,
    media_start_sec: float,
    media_end_sec: float,
    related_score_transition: Dict[str, Any],
    supporting_frame_ids: Sequence[str],
    supporting_video_windows: Sequence[Dict[str, Any]],
    verification_status: str,
    confidence: float,
    uncertainty: float,
    live_or_replay: str = "unknown",
    notes: str = "",
) -> Dict[str, Any]:
    """Build a delivery-schema-compatible Goal event for strip re-inference."""
    return {
        "event_id": inferred_event_id,
        "event_type_id": "soccer_goal",
        "event_type": "Goal",
        "event_type_zh": "进球",
        "comment_label": "Goal",
        "is_model_target": True,
        "media_time": {
            "event_time_sec": float(media_time_sec),
            "start_time_sec": float(media_start_sec),
            "end_time_sec": float(media_end_sec),
        },
        "attributes": {},
        "video_context": {
            "broadcast_phase": "LIVE" if live_or_replay == "live" else None,
            "is_replay": live_or_replay == "replay",
            "is_slow_motion": False,
            "replay_of_event_id": None,
        },
        "source": "video_agent_inferred",
        "inferred_event_id": inferred_event_id,
        "supporting_frame_ids": list(supporting_frame_ids),
        "supporting_video_windows": list(supporting_video_windows),
        "verification_status": verification_status,
        "confidence": float(confidence),
        "uncertainty": float(uncertainty),
        "related_score_transition": related_score_transition,
        "notes": notes or "Inferred Goal from video evidence; not from gold",
        "render_ready": False,
    }


def should_emit_inferred_goal(evidence: Dict[str, Any]) -> bool:
    """Only emit when shot+net frame evidence localized and not pure replay."""
    if evidence.get("grade") != "action_localized":
        return False
    if evidence.get("verification_status") != "verified_action":
        return False
    if evidence.get("live_or_replay") == "replay":
        return False
    if not evidence.get("shooting_action_evidence"):
        return False
    if not evidence.get("goal_result_evidence"):
        return False
    return True


def merge_enhanced_events_payload(
    *,
    original_events_path: Path,
    inferred_goals: Sequence[Dict[str, Any]],
    match_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return separate original + inferred + merged lists (does not write over source)."""
    raw = json.loads(Path(original_events_path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("events"), list):
        raise ValueError("original events.json invalid")
    for bad in ("causal_chains", "causal", "story_graph"):
        if bad in raw:
            raise ValueError(f"refusing original payload with {bad}")

    original = list(raw["events"])
    inferred = [copy.deepcopy(g) for g in inferred_goals if g.get("source") == "video_agent_inferred"]
    # Only verified inferred goals enter the strip re-run merge.
    usable = [
        g
        for g in inferred
        if str(g.get("verification_status")) == "verified_action"
    ]
    merged = original + usable
    # Sort by event_time for stable timeline
    def _t(e: Dict[str, Any]) -> float:
        mt = e.get("media_time") or {}
        if mt.get("event_time_sec") is not None:
            return float(mt["event_time_sec"])
        return float(mt.get("start_time_sec") or 0.0)

    merged_sorted = sorted(merged, key=_t)
    return {
        "schema": "v2_enhanced_events_bundle_v1",
        "match_id": match_id or raw.get("match_id"),
        "original_events_path": str(original_events_path),
        "n_original": len(original),
        "n_inferred_total": len(inferred),
        "n_inferred_verified_merged": len(usable),
        "n_merged": len(merged_sorted),
        "original_events": original,
        "inferred_events": inferred,
        "merged_events_for_strip": merged_sorted,
        "forbidden": ["overwrite_original_events_json", "*_causal.json", "strip_gold"],
        "render_ready": False,
    }


def write_enhanced_bundle(out_dir: Path, bundle: Dict[str, Any]) -> Dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    p_inf = out_dir / "inferred_goal_events.json"
    p_inf.write_text(
        json.dumps(
            {
                "schema": "v2_inferred_goal_events_v1",
                "events": bundle.get("inferred_events") or [],
                "n": bundle.get("n_inferred_total"),
                "render_ready": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    paths["inferred"] = p_inf

    p_merged = out_dir / "enhanced_events_for_strip.json"
    # Delivery-like envelope for strip (events only + metadata)
    envelope = {
        "schema_version": "v2_enhanced_for_strip",
        "match_id": bundle.get("match_id"),
        "events": bundle.get("merged_events_for_strip") or [],
        "source_original": bundle.get("original_events_path"),
        "n_original": bundle.get("n_original"),
        "n_inferred_verified_merged": bundle.get("n_inferred_verified_merged"),
        "note": "Merged for causal_chain6 only; original file untouched",
    }
    p_merged.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths["merged"] = p_merged

    p_meta = out_dir / "enhanced_events_meta.json"
    meta = {k: v for k, v in bundle.items() if k not in ("original_events", "merged_events_for_strip")}
    # keep inferred in meta file via inferred path reference
    meta["inferred_events"] = bundle.get("inferred_events") or []
    p_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths["meta"] = p_meta
    return paths
