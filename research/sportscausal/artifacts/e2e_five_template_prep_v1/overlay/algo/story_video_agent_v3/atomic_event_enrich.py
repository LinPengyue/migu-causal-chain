"""Merge missing atomic events from *_causal.json into delivery events JSON.

Only copies atom fields: type, t_ms, and necessary media/replay flags.
Never copies chain_category, subtype, edges, segment windows, or story roles.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _norm_type(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    return s


def _event_time_sec(e: Dict[str, Any]) -> Optional[float]:
    mt = e.get("media_time") or {}
    t = mt.get("event_time_sec")
    if t is None:
        t = mt.get("start_time_sec")
    return float(t) if t is not None else None


def extract_atomic_events(causal: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten causal_chains to unique atoms (type + t_ms).

    is_replay on an atom = False if ANY containing chain is non-replay,
    else True if all containing chains are replay. Chain category is discarded.
    """
    buckets: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for ch in causal.get("causal_chains") or []:
        chain_replay = bool(ch.get("is_replay"))
        for e in ch.get("events") or []:
            typ = _norm_type(e.get("type_en") or e.get("type"))
            if not typ or e.get("t_ms") is None:
                continue
            t_ms = int(round(float(e["t_ms"])))
            key = (typ, t_ms)
            if key not in buckets:
                buckets[key] = {
                    "type_en": typ,
                    "type_zh": e.get("type") if e.get("type") != typ else None,
                    "t_ms": t_ms,
                    "source_event_ids": [],
                    "seen_live": False,
                    "seen_replay": False,
                }
            row = buckets[key]
            eid = e.get("event_id")
            if eid and eid not in row["source_event_ids"]:
                row["source_event_ids"].append(str(eid))
            if chain_replay:
                row["seen_replay"] = True
            else:
                row["seen_live"] = True
    out = []
    for row in buckets.values():
        # Prefer LIVE occurrence when both exist
        is_replay = bool(row["seen_replay"] and not row["seen_live"])
        out.append({
            "type_en": row["type_en"],
            "type_zh": row["type_zh"],
            "t_ms": row["t_ms"],
            "is_replay": is_replay,
            "source_event_ids": row["source_event_ids"],
            "provenance": "causal_atom_fill",
        })
    out.sort(key=lambda r: (r["t_ms"], r["type_en"]))
    return out


def _raw_has_equivalent(
    raw_events: Sequence[Dict[str, Any]],
    *,
    typ: str,
    t_ms: int,
    tol_ms: int = 500,
) -> bool:
    typ_l = typ.lower().replace(" ", "_")
    for e in raw_events:
        t = _event_time_sec(e)
        if t is None:
            continue
        if abs(int(round(t * 1000)) - t_ms) > tol_ms:
            continue
        raw_typ = _norm_type(e.get("event_type") or e.get("event_type_zh"))
        if raw_typ.lower().replace(" ", "_") == typ_l:
            return True
        # Chinese/English soft match for Goal
        if typ_l in {"goal", "进球"} and raw_typ.lower() in {"goal", "进球", "own_goal"}:
            return True
    return False


def atom_to_delivery_event(atom: Dict[str, Any], *, seq: int) -> Dict[str, Any]:
    t_sec = float(atom["t_ms"]) / 1000.0
    typ = atom["type_en"]
    eid = f"atom_fill_{seq:04d}_{typ}_{atom['t_ms']}"
    # Keep delivery-shaped Goal so 8.31 norm_type → goal
    event_type = typ
    event_type_zh = atom.get("type_zh") or (
        "进球" if typ.lower() == "goal" else None
    )
    return {
        "event_id": eid,
        "event_type": event_type,
        "event_type_zh": event_type_zh,
        "event_type_id": f"soccer_{typ.lower()}" if typ else None,
        "media_time": {
            "event_time_sec": t_sec,
            "start_time_sec": t_sec,
            "end_time_sec": t_sec + 2.0,
        },
        "video_context": {
            "broadcast_phase": "REPLAY" if atom.get("is_replay") else "LIVE",
            "is_replay": bool(atom.get("is_replay")),
            "is_slow_motion": False,
            "replay_of_event_id": None,
        },
        "attributes": {},
        "scores": {},
        "notes": "",
        "comment_label": typ,
        "is_model_target": False,
        "enrichment": {
            "provenance": "causal_atom_fill",
            "source_event_ids": list(atom.get("source_event_ids") or []),
            "copied_fields": ["type", "t_ms", "is_replay"],
            "forbidden_copied": [
                "chain_category",
                "causal_chain_subtype",
                "segment_time_video",
                "edges",
                "story",
            ],
        },
    }


def enrich_delivery_events(
    raw: Dict[str, Any],
    causal: Dict[str, Any],
    *,
    tol_ms: int = 500,
) -> Dict[str, Any]:
    atoms = extract_atomic_events(causal)
    raw_events = list(raw.get("events") or [])
    injected: List[Dict[str, Any]] = []
    skipped_dup = 0
    by_type: Dict[str, int] = defaultdict(int)
    for atom in atoms:
        if _raw_has_equivalent(raw_events, typ=atom["type_en"], t_ms=atom["t_ms"], tol_ms=tol_ms):
            skipped_dup += 1
            continue
        ev = atom_to_delivery_event(atom, seq=len(injected))
        injected.append(ev)
        by_type[atom["type_en"]] += 1

    merged = list(raw_events) + injected
    # Stable chronological order
    def _sort_key(e: Dict[str, Any]) -> Tuple[float, str]:
        t = _event_time_sec(e)
        return (t if t is not None else 1e18, str(e.get("event_id") or ""))

    merged.sort(key=_sort_key)
    out = dict(raw)
    out["events"] = merged
    out["enrichment_report"] = {
        "schema": "v3_atomic_enrich_v1",
        "n_raw_events": len(raw_events),
        "n_causal_atoms_unique": len(atoms),
        "n_injected": len(injected),
        "n_skipped_duplicate": skipped_dup,
        "injected_by_type": dict(by_type),
        "n_goal_injected": by_type.get("Goal", 0) + by_type.get("goal", 0),
        "n_goal_injected_live": sum(
            1 for e in injected
            if str(e.get("event_type")).lower() == "goal"
            and not (e.get("video_context") or {}).get("is_replay")
        ),
        "n_goal_injected_replay": sum(
            1 for e in injected
            if str(e.get("event_type")).lower() == "goal"
            and (e.get("video_context") or {}).get("is_replay")
        ),
        "note": (
            "Atoms only; no chain_category/subtype/windows/edges. "
            "is_replay prefers LIVE when any non-replay occurrence exists."
        ),
    }
    return out



def enrich_with_independent_atoms(
    raw: Dict[str, Any], annotations: Dict[str, Any], *, tol_ms: int = 500,
) -> Dict[str, Any]:
    """Merge *independent event-level* annotations, never causal/story labels.

    Accept only an explicit `atomic_events` list. The supplied record is a
    detector/annotator observation, not a verified first-live video proof.
    """
    if not isinstance(annotations, dict) or not isinstance(annotations.get("atomic_events"), list):
        raise ValueError("independent atomic input requires atomic_events list")
    if any(k in annotations for k in ("causal_chains", "story_chains", "story_graph", "edges")):
        raise ValueError("causal_or_story_labels_forbidden_in_independent_atoms")
    raw_events = list(raw.get("events") or [])
    injected = []
    duplicates = 0
    for index, a in enumerate(annotations["atomic_events"]):
        if not isinstance(a, dict):
            raise ValueError("atomic_event_must_be_object")
        if any(k in a for k in (
            "chain_category", "causal_chain_subtype", "causal_chains",
            "story_role", "story", "edges", "segment_time_video",
        )):
            raise ValueError("causal_or_story_field_forbidden_in_atomic_event")
        typ = _norm_type(a.get("event_type") or a.get("type_en"))
        t_ms = a.get("t_ms")
        if not typ or t_ms is None:
            raise ValueError("atomic_event_requires_type_and_t_ms")
        try:
            t_ms = int(round(float(t_ms)))
        except (TypeError, ValueError, OverflowError):
            raise ValueError("atomic_event_invalid_t_ms") from None
        if t_ms < 0:
            raise ValueError("atomic_event_negative_t_ms")
        if _raw_has_equivalent(raw_events + injected, typ=typ, t_ms=t_ms, tol_ms=tol_ms):
            duplicates += 1
            continue
        # Unknown broadcast status is NOT LIVE. Never manufacture first-live.
        broadcast = str(a.get("broadcast_phase") or "UNKNOWN").upper()
        if broadcast not in {"LIVE", "REPLAY", "UNKNOWN"}:
            raise ValueError("atomic_event_invalid_broadcast_phase")
        atom = {
            "type_en": typ, "type_zh": a.get("event_type_zh"),
            "t_ms": t_ms, "is_replay": broadcast == "REPLAY",
            "source_event_ids": [str(a.get("event_id"))] if a.get("event_id") else [],
        }
        ev = atom_to_delivery_event(atom, seq=index)
        ev["event_id"] = f"independent_atom_{index:05d}_{typ}_{t_ms}"
        ev["video_context"]["broadcast_phase"] = broadcast
        ev["video_context"]["is_replay"] = broadcast == "REPLAY"
        ev["enrichment"]["provenance"] = "independent_atomic_annotation"
        ev["enrichment"]["broadcast_status_verified"] = False
        injected.append(ev)
    merged = raw_events + injected
    merged.sort(key=lambda e: (_event_time_sec(e) if _event_time_sec(e) is not None else 1e18, str(e.get("event_id") or "")))
    out = dict(raw)
    out["events"] = merged
    out["enrichment_report"] = {
        "schema": "v3_atomic_enrich_v1",
        "n_raw_events": len(raw_events),
        "n_causal_atoms_unique": 0,
        "n_injected": len(injected),
        "n_skipped_duplicate": duplicates,
        "injected_by_type": dict(Counter(e["event_type"] for e in injected)),
        "n_goal_injected": sum(str(e["event_type"]).lower() == "goal" for e in injected),
        "n_goal_injected_live": sum(str(e["event_type"]).lower() == "goal" and e["video_context"]["broadcast_phase"] == "LIVE" for e in injected),
        "n_goal_injected_replay": sum(str(e["event_type"]).lower() == "goal" and e["video_context"]["broadcast_phase"] == "REPLAY" for e in injected),
        "note": "Independent event-level annotations only; broadcast flags are unverified metadata.",
    }
    return out


def enrich_files(
    *,
    events_path: Path,
    causal_path: Optional[Path] = None,
    independent_atoms_path: Optional[Path] = None,
    out_events_path: Path,
    out_report_path: Optional[Path] = None,
) -> Dict[str, Any]:
    raw = json.loads(Path(events_path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("events"), list):
        raise ValueError("events input must be a delivery event object with events list")
    # Official no-gold evaluation is raw-only. Do not manufacture human Goal
    # atoms from the scorer, frame times or annotator data.
    if causal_path is not None and independent_atoms_path is not None:
        raise ValueError("causal_and_independent_atoms_mutually_exclusive")
    if independent_atoms_path is not None:
        annotations = json.loads(Path(independent_atoms_path).read_text(encoding="utf-8"))
        enriched = enrich_with_independent_atoms(raw, annotations)
        input_mode = "INDEPENDENT_ATOMIC_ANNOTATED"
    elif causal_path is None:
        enriched = enrich_delivery_events(raw, {"causal_chains": []})
        input_mode = "RAW_EVENTS_ONLY"
    else:
        causal = json.loads(Path(causal_path).read_text(encoding="utf-8"))
        # Preserve the historical development mode without treating it as
        # benchmark-eligible Agent inference.
        if not isinstance(causal, dict) or "causal_chains" not in causal:
            raise ValueError("causal file must contain causal_chains for atom extraction only")
        enriched = enrich_delivery_events(raw, causal)
        input_mode = "HUMAN_ATOM_ENRICHED_DEV"
    report = enriched.pop("enrichment_report")
    out_events_path = Path(out_events_path)
    out_events_path.parent.mkdir(parents=True, exist_ok=True)
    out_events_path.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report["out_events"] = str(out_events_path)
    report["source_events"] = str(events_path)
    report["source_causal_atoms_only"] = str(causal_path) if causal_path else None
    report["input_mode"] = input_mode
    report["human_annotation_atoms_used"] = causal_path is not None or independent_atoms_path is not None
    report["independent_atomic_annotations_used"] = independent_atoms_path is not None
    report["source_independent_atoms"] = str(independent_atoms_path) if independent_atoms_path else None
    report["eligible_for_raw_only_evaluation"] = causal_path is None and independent_atoms_path is None
    report["eligible_for_event_annotated_evaluation"] = causal_path is None
    report["goal_recovery_reliance"] = (
        "human_atoms_plus_raw_events_dev_only" if causal_path is not None
        else ("independent_annotated_atoms_plus_raw_events" if independent_atoms_path is not None
              else "raw_event_score_transitions_and_actions")
    )
    if out_report_path:
        Path(out_report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_report_path).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return report
