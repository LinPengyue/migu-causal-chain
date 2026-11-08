"""Final-delivery goal evidence binding + Goal Recovery lineage (match-agnostic).

RELEASE_READY must use the *final delivery EDL* first-live statuses, never V3-R
historical aggregates alone. Prior visual rows may be inherited only when source
video SHA256, segment media window, and evidence window all match.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .first_live_chain_audit import (
    FIRST_LIVE_STATUSES,
    audit_retained_goal_first_live,
    is_goal_action_segment,
    _edl_segments,
)
from .pipeline import dump
from .story_timeline import build_story_timeline

_PTS_TOL = 0.05


def sha256_file(
    path: Path,
    *,
    max_bytes: Optional[int] = None,
    cache_path: Optional[Path] = None,
) -> Optional[str]:
    """Content SHA256 of source video (cached when cache_path provided)."""
    p = Path(path)
    if not p.is_file():
        return None
    st = p.stat()
    if cache_path is not None and Path(cache_path).is_file():
        try:
            cached = json.loads(Path(cache_path).read_text(encoding="utf-8"))
            if (
                cached.get("path") == str(p.resolve())
                and int(cached.get("size") or -1) == int(st.st_size)
                and int(cached.get("mtime_ns") or -1) == int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
                and cached.get("sha256")
            ):
                return str(cached["sha256"])
        except Exception:  # noqa: BLE001
            pass
    h = hashlib.sha256()
    n = 0
    with p.open("rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            n += len(chunk)
            if max_bytes is not None and n >= max_bytes:
                break
    digest = h.hexdigest()
    if cache_path is not None:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        Path(cache_path).write_text(
            json.dumps(
                {
                    "path": str(p.resolve()),
                    "size": int(st.st_size),
                    "mtime_ns": int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
                    "sha256": digest,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return digest


def _pts_eq(a: Any, b: Any, tol: float = _PTS_TOL) -> bool:
    try:
        if a is None or b is None:
            return a is None and b is None
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def _window_key(mi: Any, mo: Any) -> Optional[Tuple[float, float]]:
    try:
        if mi is None or mo is None:
            return None
        return (round(float(mi), 3), round(float(mo), 3))
    except (TypeError, ValueError):
        return None


def can_inherit_prior_evidence(
    *,
    segment: Mapping[str, Any],
    prior_row: Mapping[str, Any],
    source_video_sha256: Optional[str],
    prior_video_sha256: Optional[str],
) -> Tuple[bool, str]:
    """Inherit only when video identity + media window + evidence window agree."""
    if not source_video_sha256 or not prior_video_sha256:
        return False, "missing_video_sha256"
    if source_video_sha256 != prior_video_sha256:
        return False, "source_video_sha256_mismatch"

    sid = str(segment.get("segment_id") or segment.get("id") or "")
    prior_sid = str(prior_row.get("segment_id") or "")
    if sid and prior_sid and sid != prior_sid:
        # Allow same role+window under renamed id only if windows match exactly below.
        role = str(segment.get("role") or "")
        prior_role = str(prior_row.get("role") or "")
        if role and prior_role and role != prior_role:
            return False, "segment_id_and_role_mismatch"

    mi, mo = segment.get("media_in"), segment.get("media_out")
    if not _pts_eq(mi, prior_row.get("media_in")) or not _pts_eq(mo, prior_row.get("media_out")):
        return False, "source_media_window_changed"

    # Evidence window: prefer explicit source_pts / evidence fields on prior row.
    evid = prior_row.get("source_pts") or {}
    e_mi = evid.get("media_in", prior_row.get("media_in"))
    e_mo = evid.get("media_out", prior_row.get("media_out"))
    if not _pts_eq(mi, e_mi) or not _pts_eq(mo, e_mo):
        return False, "evidence_window_mismatch"

    # Subject of verification must be the same goal action span.
    if prior_row.get("score_confirm_collision"):
        return False, "prior_score_confirm_collision_not_reusable"

    status = str(prior_row.get("first_live_status") or "UNRESOLVED")
    if status not in FIRST_LIVE_STATUSES:
        return False, "prior_status_unknown"
    return True, "ok"


def _index_prior_goals(prior_audit: Optional[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not prior_audit:
        return out
    for g in prior_audit.get("goals") or []:
        if not isinstance(g, dict):
            continue
        sid = str(g.get("segment_id") or "")
        if sid:
            out[sid] = dict(g)
        key = _window_key(g.get("media_in"), g.get("media_out"))
        if key is not None:
            out[f"pts:{key[0]}:{key[1]}"] = dict(g)
    return out


def bind_edl_goal_evidence(
    *,
    label: str,
    edl: Any,
    video: Path,
    out_dir: Path,
    events_path: Optional[Path] = None,
    goal_recovery: Optional[Mapping[str, Any]] = None,
    prior_audits: Optional[Sequence[Mapping[str, Any]]] = None,
    source_video_sha256: Optional[str] = None,
    enable_paid_vlm: bool = False,
) -> Dict[str, Any]:
    """Build per-goal evidence for one EDL (delivery or candidate). Re-audit when needed."""
    if enable_paid_vlm:
        raise RuntimeError("Paid VLM disabled; prepare pack and wait for approval")

    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    video = Path(video)
    video_sha = source_video_sha256 or sha256_file(video)
    segs = [s for s in _edl_segments(edl) if is_goal_action_segment(s)]

    prior_maps = []
    for pa in prior_audits or []:
        prior_maps.append({
            "video_sha256": (pa or {}).get("source_video_sha256"),
            "by": _index_prior_goals(pa),
            "schema": (pa or {}).get("schema"),
        })

    inherited: List[Dict[str, Any]] = []
    need_audit: List[Dict[str, Any]] = []
    inherit_decisions: List[Dict[str, Any]] = []

    for seg in segs:
        sid = str(seg.get("segment_id") or seg.get("id") or "")
        key = _window_key(seg.get("media_in"), seg.get("media_out"))
        chosen = None
        reason = "no_prior_row"
        for pm in prior_maps:
            cand = pm["by"].get(sid) or (pm["by"].get(f"pts:{key[0]}:{key[1]}") if key else None)
            if not cand:
                continue
            prior_sha = pm.get("video_sha256") or cand.get("source_video_sha256")
            ok, why = can_inherit_prior_evidence(
                segment=seg,
                prior_row=cand,
                source_video_sha256=video_sha,
                prior_video_sha256=prior_sha,
            )
            if ok:
                chosen = dict(cand)
                reason = f"inherited_from_{pm.get('schema') or 'prior'}"
                break
            reason = why
        inherit_decisions.append({
            "segment_id": sid,
            "inherited": chosen is not None,
            "reason": reason,
            "media_in": seg.get("media_in"),
            "media_out": seg.get("media_out"),
        })
        if chosen is not None:
            row = dict(chosen)
            row["segment_id"] = sid
            row["role"] = seg.get("role") or row.get("role")
            row["source_media_in"] = seg.get("media_in")
            row["source_media_out"] = seg.get("media_out")
            row["source_video_sha256"] = video_sha
            row["evidence_binding"] = "inherited_identical_window"
            row["inherited"] = True
            inherited.append(row)
        else:
            need_audit.append(dict(seg))

    fresh_audit: Dict[str, Any] = {
        "schema": "v3a_first_live_chain_audit_v1",
        "goals": [],
        "status_counts": {s: 0 for s in FIRST_LIVE_STATUSES},
        "n_goal_anchors": 0,
    }
    if need_audit:
        fresh_audit = audit_retained_goal_first_live(
            video=video,
            edl=need_audit,
            out_dir=dest / "reaudit",
            events_path=events_path,
            goal_recovery=goal_recovery,
            enable_paid_vlm=False,
        )
        for g in fresh_audit.get("goals") or []:
            g["source_media_in"] = g.get("media_in")
            g["source_media_out"] = g.get("media_out")
            g["source_video_sha256"] = video_sha
            g["evidence_binding"] = "reverified_after_window_or_subject_change"
            g["inherited"] = False

    goals = list(inherited) + list(fresh_audit.get("goals") or [])
    # Keep EDL order.
    by_sid = {str(g.get("segment_id")): g for g in goals}
    ordered = []
    for seg in segs:
        sid = str(seg.get("segment_id") or seg.get("id") or "")
        g = by_sid.get(sid)
        if g is None:
            g = {
                "segment_id": sid,
                "role": seg.get("role"),
                "source_media_in": seg.get("media_in"),
                "source_media_out": seg.get("media_out"),
                "media_in": seg.get("media_in"),
                "media_out": seg.get("media_out"),
                "source_video_sha256": video_sha,
                "first_live_status": "UNRESOLVED",
                "evidence_binding": "missing_audit_row",
                "inherited": False,
                "visual_verified": False,
            }
        ordered.append(g)

    counts = {s: 0 for s in FIRST_LIVE_STATUSES}
    for g in ordered:
        st = str(g.get("first_live_status") or "UNRESOLVED")
        if st not in counts:
            st = "UNRESOLVED"
            g["first_live_status"] = st
        counts[st] += 1

    # Never upgrade UNRESOLVED→VERIFIED here.
    for g in ordered:
        if g.get("first_live_status") == "FIRST_LIVE_VERIFIED" and not (
            g.get("agent_auto_verified") and g.get("goal_action_verified_ok")
        ):
            g["first_live_status"] = "UNRESOLVED"
            g["demoted_false_verified"] = True

    counts = {s: 0 for s in FIRST_LIVE_STATUSES}
    for g in ordered:
        counts[str(g.get("first_live_status") or "UNRESOLVED")] += 1

    manifest = {
        "schema": "v3a_final_goal_evidence_manifest_v1",
        "label": label,
        "source_video": str(video),
        "source_video_sha256": video_sha,
        "n_goal_anchors": len(ordered),
        "status_counts": counts,
        "n_inherited": sum(1 for g in ordered if g.get("inherited")),
        "n_reverified": sum(1 for g in ordered if not g.get("inherited")),
        "any_first_live_verified": counts.get("FIRST_LIVE_VERIFIED", 0) > 0,
        "any_replay_on_retained": counts.get("REPLAY_DETECTED", 0) > 0,
        "all_resolved_verified": (
            len(ordered) > 0 and counts.get("FIRST_LIVE_VERIFIED", 0) == len(ordered)
        ),
        "inherit_decisions": inherit_decisions,
        "goals": ordered,
        "paid_api_calls": 0,
        "success_claimed": False,
        "note": (
            "Evidence bound to this EDL only. Candidate and delivery manifests are separate. "
            "Inheritance requires identical video SHA + media window + evidence window."
        ),
    }
    dump(dest / "final_goal_evidence_manifest.json", manifest)
    return manifest


def _parse_recovery_id_from_event(eid: str) -> Optional[str]:
    s = str(eid or "")
    # v3_goal_goalcand_01_01_to_11 → goalcand_01_01_to_11
    m = re.match(r"^v3_goal_(goalcand_.+)$", s)
    if m:
        return m.group(1)
    # causal:pred_0007:atom_fill_... — not a recovery id
    if s.startswith("goalcand_"):
        return s
    return None


def _chain_for_event(
    predicted_causal: Mapping[str, Any],
    event_id: str,
) -> Optional[Dict[str, Any]]:
    for ch in predicted_causal.get("causal_chains") or []:
        for e in ch.get("events") or []:
            if str(e.get("event_id")) == str(event_id):
                return dict(ch)
        # also match annotation-qualified ids
        ann = str(ch.get("annotation_id") or "")
        for e in ch.get("events") or []:
            qual = f"causal:{ann}:{e.get('event_id')}"
            if qual == str(event_id):
                return dict(ch)
    return None


def build_goal_lineage_report(
    *,
    edl: Any,
    predicted_causal: Mapping[str, Any],
    goal_recovery: Mapping[str, Any],
    story_graph: Optional[Mapping[str, Any]] = None,
    evidence_manifest: Optional[Mapping[str, Any]] = None,
    final_mp4: Optional[Path] = None,
) -> Dict[str, Any]:
    """Recovery Candidate → Predicted Causal → Story Graph → EDL → Final MP4."""
    timeline = build_story_timeline(edl)
    tl_by_sid = {
        str(s.get("segment_id")): s for s in (timeline.get("segments") or [])
    }
    evid_by_sid = {
        str(g.get("segment_id")): g
        for g in ((evidence_manifest or {}).get("goals") or [])
    }
    recovery_by_id = {
        str(c.get("candidate_id")): c
        for c in (goal_recovery.get("candidates") or [])
        if isinstance(c, dict)
    }
    graph_nodes = {
        str(n.get("id")): n
        for n in ((story_graph or {}).get("nodes") or [])
        if isinstance(n, dict)
    }

    rows: List[Dict[str, Any]] = []
    for seg in _edl_segments(edl):
        if not is_goal_action_segment(seg):
            continue
        sid = str(seg.get("segment_id") or "")
        event_ids = list(seg.get("event_ids") or [])
        primary_eid = str(event_ids[0]) if event_ids else None
        recovery_id = None
        for eid in event_ids:
            recovery_id = _parse_recovery_id_from_event(str(eid))
            if recovery_id:
                break
        # Also try matching by PTS to recovery when event_id is strip/causal atom.
        rec = recovery_by_id.get(recovery_id) if recovery_id else None
        if rec is None and seg.get("media_in") is not None:
            mi = float(seg["media_in"])
            best = None
            best_d = None
            for c in recovery_by_id.values():
                action = c.get("goal_action_sec")
                if action is None:
                    continue
                d = abs(float(action) - mi)
                if d <= 45.0 and (best_d is None or d < best_d):
                    best, best_d = c, d
            if best is not None:
                rec = best
                recovery_id = str(best.get("candidate_id"))

        chain = _chain_for_event(predicted_causal, primary_eid) if primary_eid else None
        if chain is None and recovery_id:
            # Find recovery-sourced chain by goal_candidate_id
            for ch in predicted_causal.get("causal_chains") or []:
                if str(ch.get("goal_candidate_id") or "") == str(recovery_id):
                    chain = dict(ch)
                    break
                for e in ch.get("events") or []:
                    if str(e.get("event_id")) == f"v3_goal_{recovery_id}":
                        chain = dict(ch)
                        break

        graph_seg = graph_nodes.get(sid)
        graph_event = None
        if primary_eid:
            graph_event = graph_nodes.get(f"event:{primary_eid}")
        if graph_event is None and recovery_id:
            graph_event = graph_nodes.get(f"event:v3_goal_{recovery_id}")

        tl = tl_by_sid.get(sid) or {}
        evid = evid_by_sid.get(sid) or {}

        in_final_video = bool(seg.get("include_in_cut", True)) and tl.get("has_media_window")
        rows.append({
            "segment_id": sid,
            "role": seg.get("role"),
            "recovery_candidate_id": recovery_id,
            "score_before": (rec or {}).get("score_before"),
            "score_after": (rec or {}).get("score_after"),
            "goal_action_sec": (rec or {}).get("goal_action_sec") or seg.get("goal_anchor_t_sec"),
            "score_confirmation_sec": (rec or {}).get("score_confirmation_sec"),
            "source_media_in": seg.get("media_in"),
            "source_media_out": seg.get("media_out"),
            "predicted_causal_chain_id": (chain or {}).get("annotation_id"),
            "prediction_source": (chain or {}).get("prediction_source"),
            "causal_event_ids": event_ids,
            "story_graph_segment_node": (graph_seg or {}).get("id"),
            "story_graph_event_node": (graph_event or {}).get("id"),
            "story_in": tl.get("story_in"),
            "story_out": tl.get("story_out"),
            "in_final_mp4": bool(in_final_video),
            "final_mp4": str(final_mp4) if final_mp4 else None,
            "first_live_status": evid.get("first_live_status") or "UNRESOLVED",
            "evidence_binding": evid.get("evidence_binding"),
            "lineage_complete": bool(
                sid
                and seg.get("media_in") is not None
                and in_final_video
                and (chain is not None or recovery_id is not None or primary_eid)
            ),
            "gaps": [
                g for g, ok in (
                    ("missing_recovery_candidate", rec is None and primary_eid and str(primary_eid).startswith("v3_goal_")),
                    ("missing_predicted_causal_chain", chain is None),
                    ("missing_story_graph_segment", graph_seg is None),
                    ("not_in_final_mp4_timeline", not in_final_video),
                    ("first_live_unresolved", str(evid.get("first_live_status") or "UNRESOLVED") != "FIRST_LIVE_VERIFIED"),
                )
                if ok
            ],
        })

    n_complete = sum(1 for r in rows if r.get("lineage_complete") and not r.get("gaps"))
    # gaps always includes first_live_unresolved in zero-cost — lineage structural completeness separate
    n_struct = sum(
        1 for r in rows
        if r.get("segment_id")
        and r.get("source_media_in") is not None
        and r.get("in_final_mp4")
        and (r.get("predicted_causal_chain_id") or r.get("recovery_candidate_id") or r.get("causal_event_ids"))
        and r.get("story_graph_segment_node")
    )

    report = {
        "schema": "v3a_goal_lineage_report_v1",
        "n_final_goal_segments": len(rows),
        "n_structurally_traced_to_mp4": n_struct,
        "n_lineage_rows": len(rows),
        "entered_predicted_causal_alone_insufficient": True,
        "goals": rows,
        "duplicate_segment_ids": [
            sid for sid, n in (
                (s, sum(1 for r in rows if r["segment_id"] == s))
                for s in {r["segment_id"] for r in rows}
            ) if n > 1
        ],
        "note": (
            "Each retained EDL goal must trace Recovery/Causal → Graph → EDL → story timeline. "
            "entered_predicted_causal=true alone never proves presence in final MP4."
        ),
    }
    return report


def build_delivery_and_candidate_evidence(
    *,
    delivery_edl: Any,
    candidate_edl: Optional[Any],
    video: Path,
    out_dir: Path,
    events_path: Optional[Path] = None,
    goal_recovery: Optional[Mapping[str, Any]] = None,
    prior_v3r_audit: Optional[Mapping[str, Any]] = None,
    predicted_causal: Optional[Mapping[str, Any]] = None,
    story_graph: Optional[Mapping[str, Any]] = None,
    final_mp4: Optional[Path] = None,
) -> Dict[str, Any]:
    """Produce delivery + candidate manifests and lineage for final packaging."""
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    video_sha = sha256_file(Path(video), cache_path=dest / "source_video.sha256.json")

    # Stamp prior audit with video sha if missing (same source match video).
    priors = []
    if prior_v3r_audit:
        pa = dict(prior_v3r_audit)
        pa.setdefault("source_video_sha256", video_sha)
        for g in pa.get("goals") or []:
            if isinstance(g, dict):
                g.setdefault("source_video_sha256", video_sha)
        priors.append(pa)

    delivery_manifest = bind_edl_goal_evidence(
        label="final_delivery",
        edl=delivery_edl,
        video=video,
        out_dir=dest / "delivery",
        events_path=events_path,
        goal_recovery=goal_recovery,
        prior_audits=priors,
        source_video_sha256=video_sha,
    )
    # Canonical path expected by auditors.
    dump(dest / "final_goal_evidence_manifest.json", delivery_manifest)

    candidate_manifest = None
    if candidate_edl is not None:
        # Candidate must not silently reuse delivery conclusions when windows differ.
        cand_priors = list(priors)
        # Do NOT pass delivery_manifest as inheritable prior for candidate — separate track.
        candidate_manifest = bind_edl_goal_evidence(
            label="v3a_candidate",
            edl=candidate_edl,
            video=video,
            out_dir=dest / "candidate",
            events_path=events_path,
            goal_recovery=goal_recovery,
            prior_audits=cand_priors,
            source_video_sha256=video_sha,
        )
        dump(dest / "candidate_goal_evidence_manifest.json", candidate_manifest)

    lineage = build_goal_lineage_report(
        edl=delivery_edl,
        predicted_causal=predicted_causal or {},
        goal_recovery=goal_recovery or {},
        story_graph=story_graph,
        evidence_manifest=delivery_manifest,
        final_mp4=final_mp4,
    )
    dump(dest / "goal_lineage_report.json", lineage)

    return {
        "delivery": delivery_manifest,
        "candidate": candidate_manifest,
        "lineage": lineage,
        "source_video_sha256": video_sha,
    }
