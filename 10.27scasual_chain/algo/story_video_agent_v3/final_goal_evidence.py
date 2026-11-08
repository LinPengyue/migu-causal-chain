"""Final-delivery goal evidence binding + Goal Recovery lineage (match-agnostic).

RELEASE_READY must use the *final delivery EDL* first-live statuses, never V3-R
historical aggregates alone. Prior visual rows may be inherited only when a
*trusted* historical source-video SHA256 is present and matches, and both the
EDL media window and the actual observation window agree. Never stamp the
current video SHA onto historical evidence.
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

LINEAGE_STRICT = "STRICT_COMPLETE"
LINEAGE_INFERRED = "INFERRED"
LINEAGE_UNRESOLVED = "UNRESOLVED"


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
                and int(cached.get("mtime_ns") or -1) == int(
                    getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
                )
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


def _included_in_cut(seg: Mapping[str, Any]) -> bool:
    return seg.get("include_in_cut", True) is not False


def goal_identity_key(seg: Mapping[str, Any]) -> str:
    """Stable goal identity — role + event_ids, not PTS alone."""
    sid = str(seg.get("segment_id") or seg.get("id") or "")
    role = str(seg.get("role") or seg.get("narrative_role") or "")
    eids = seg.get("event_ids") or []
    if isinstance(eids, list):
        eid_part = "|".join(str(x) for x in eids)
    else:
        eid_part = str(eids)
    return f"{role}::{eid_part}::{sid}"


def observation_window_from_row(row: Mapping[str, Any]) -> Optional[Tuple[float, float]]:
    """Actual observed/evidence window — not merely the EDL media span."""
    for key in ("observation_window", "evidence_window", "observed_pts"):
        ow = row.get(key)
        if isinstance(ow, Mapping):
            w = _window_key(ow.get("media_in"), ow.get("media_out"))
            if w:
                return w
    clip = row.get("clip_export")
    if isinstance(clip, Mapping):
        w = _window_key(clip.get("media_in"), clip.get("media_out"))
        if w:
            return w
    # Explicit source_pts that was audited (may differ from a later EDL edit).
    sp = row.get("source_pts")
    if isinstance(sp, Mapping):
        w = _window_key(sp.get("media_in"), sp.get("media_out"))
        if w:
            return w
    return None


def trusted_prior_video_sha(
    prior_audit: Optional[Mapping[str, Any]],
    prior_row: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    """Return historical source SHA only if explicitly recorded — never invent."""
    for src in (prior_row, prior_audit):
        if not isinstance(src, Mapping):
            continue
        sha = src.get("source_video_sha256") or src.get("video_sha256")
        if sha:
            return str(sha)
    return None


def can_inherit_prior_evidence(
    *,
    segment: Mapping[str, Any],
    prior_row: Mapping[str, Any],
    source_video_sha256: Optional[str],
    prior_video_sha256: Optional[str],
) -> Tuple[bool, str]:
    """Inherit only with trusted historical SHA + matching EDL & observation windows.

    Same source PTS with a different goal identity must not inherit.
    FIRST_LIVE_VERIFIED cannot be inherited when historical source SHA is missing,
    or when either side lacks a non-empty matching verifiable goal event identity.
    """
    status = str(prior_row.get("first_live_status") or "UNRESOLVED")
    if status not in FIRST_LIVE_STATUSES:
        return False, "prior_status_unknown"

    if not prior_video_sha256:
        if status == "FIRST_LIVE_VERIFIED":
            return False, "missing_prior_video_sha256_cannot_inherit_verified"
        return False, "missing_prior_video_sha256"
    if not source_video_sha256:
        return False, "missing_current_video_sha256"
    if source_video_sha256 != prior_video_sha256:
        return False, "source_video_sha256_mismatch"

    # Goal identity: role / event_ids must agree — PTS alone is insufficient.
    seg_role = str(segment.get("role") or segment.get("narrative_role") or "")
    prior_role = str(prior_row.get("role") or "")
    if seg_role and prior_role and seg_role != prior_role:
        return False, "goal_identity_role_mismatch"

    seg_eids = [str(x).strip() for x in (segment.get("event_ids") or []) if str(x).strip()]
    prior_eids = [
        str(x).strip()
        for x in (prior_row.get("event_ids") or prior_row.get("causal_event_ids") or [])
        if str(x).strip()
    ]
    if status == "FIRST_LIVE_VERIFIED":
        # VERIFIED inherit is fail-closed on event identity: both sides must carry
        # non-empty, comparable, identical event_ids. Missing either side → re-verify.
        if not seg_eids:
            return False, "verified_inherit_requires_current_event_ids"
        if not prior_eids:
            return False, "verified_inherit_requires_prior_event_ids"
        if set(seg_eids) != set(prior_eids):
            return False, "goal_identity_event_ids_mismatch"
    elif seg_eids and prior_eids and set(seg_eids) != set(prior_eids):
        return False, "goal_identity_event_ids_mismatch"

    sid = str(segment.get("segment_id") or segment.get("id") or "")
    prior_sid = str(prior_row.get("segment_id") or "")
    if sid and prior_sid and sid != prior_sid:
        # Renamed id only OK if role+events already matched (or events empty on both).
        if not (seg_role and prior_role and seg_role == prior_role):
            return False, "segment_id_mismatch_without_shared_identity"

    mi, mo = segment.get("media_in"), segment.get("media_out")
    if not _pts_eq(mi, prior_row.get("media_in")) or not _pts_eq(mo, prior_row.get("media_out")):
        return False, "source_media_window_changed"

    # Observation / evidence window must match the prior *observed* span.
    prior_obs = observation_window_from_row(prior_row)
    if prior_obs is None:
        return False, "prior_observation_window_missing"
    # Current subject window for comparison: segment media is what we will observe.
    cur_obs = _window_key(mi, mo)
    if cur_obs is None:
        return False, "current_observation_window_missing"
    if not _pts_eq(cur_obs[0], prior_obs[0]) or not _pts_eq(cur_obs[1], prior_obs[1]):
        return False, "observation_window_changed"

    if prior_row.get("score_confirm_collision"):
        return False, "prior_score_confirm_collision_not_reusable"

    return True, "ok"


def _index_prior_goals(prior_audit: Optional[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Index by segment_id and identity — not by PTS alone (avoids cross-goal inherit)."""
    out: Dict[str, Dict[str, Any]] = {}
    if not prior_audit:
        return out
    for g in prior_audit.get("goals") or []:
        if not isinstance(g, dict):
            continue
        sid = str(g.get("segment_id") or "")
        if sid:
            out[f"sid:{sid}"] = dict(g)
        out[f"id:{goal_identity_key(g)}"] = dict(g)
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
    """Build per-goal evidence for one EDL (delivery or candidate).

    Only ``include_in_cut=true`` goal-action segments count toward final anchors.
    Deleted / excluded goals are recorded separately and do not inherit into totals.
    """
    if enable_paid_vlm:
        raise RuntimeError("Paid VLM disabled; prepare pack and wait for approval")

    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    video = Path(video)
    video_sha = source_video_sha256 or sha256_file(video)

    all_goal_segs = [s for s in _edl_segments(edl) if is_goal_action_segment(s)]
    active_segs = [s for s in all_goal_segs if _included_in_cut(s)]
    deleted_segs = [s for s in all_goal_segs if not _included_in_cut(s)]

    prior_maps = []
    for pa in prior_audits or []:
        if not pa:
            continue
        # Do NOT invent / stamp current SHA onto historical audits.
        prior_maps.append({
            "video_sha256": trusted_prior_video_sha(pa),
            "by": _index_prior_goals(pa),
            "schema": (pa or {}).get("schema"),
            "raw": pa,
        })

    inherited: List[Dict[str, Any]] = []
    need_audit: List[Dict[str, Any]] = []
    inherit_decisions: List[Dict[str, Any]] = []
    missing_source_records: List[Dict[str, Any]] = []

    for seg in active_segs:
        sid = str(seg.get("segment_id") or seg.get("id") or "")
        ident = goal_identity_key(seg)
        chosen = None
        reason = "no_prior_row"
        matched_prior = None
        for pm in prior_maps:
            cand = pm["by"].get(f"sid:{sid}") or pm["by"].get(f"id:{ident}")
            if not cand:
                continue
            matched_prior = cand
            prior_sha = trusted_prior_video_sha(pm.get("raw"), cand)
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
            if why in (
                "missing_prior_video_sha256",
                "missing_prior_video_sha256_cannot_inherit_verified",
            ):
                missing_source_records.append({
                    "segment_id": sid,
                    "prior_status": cand.get("first_live_status"),
                    "reason": why,
                    "action": "reaudit_required",
                })
        inherit_decisions.append({
            "segment_id": sid,
            "goal_identity": ident,
            "inherited": chosen is not None,
            "reason": reason,
            "media_in": seg.get("media_in"),
            "media_out": seg.get("media_out"),
            "prior_observation_window": (
                list(observation_window_from_row(matched_prior))
                if matched_prior and observation_window_from_row(matched_prior)
                else None
            ),
        })
        if chosen is not None:
            row = dict(chosen)
            row["segment_id"] = sid
            row["role"] = seg.get("role") or row.get("role")
            row["event_ids"] = list(seg.get("event_ids") or row.get("event_ids") or [])
            row["source_media_in"] = seg.get("media_in")
            row["source_media_out"] = seg.get("media_out")
            # Keep historical SHA on the row; also record current for binding audit.
            row["prior_source_video_sha256"] = chosen.get("source_video_sha256") or trusted_prior_video_sha(
                None, chosen
            )
            row["source_video_sha256"] = video_sha
            row["observation_window"] = {
                "media_in": seg.get("media_in"),
                "media_out": seg.get("media_out"),
            }
            row["evidence_binding"] = "inherited_trusted_sha_and_observation_window"
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
            g["observation_window"] = {
                "media_in": g.get("media_in"),
                "media_out": g.get("media_out"),
            }
            # Preserve why we could not inherit.
            miss = next(
                (m for m in missing_source_records if m.get("segment_id") == g.get("segment_id")),
                None,
            )
            if miss:
                g["prior_source_missing"] = miss
                g["evidence_binding"] = "reverified_prior_source_sha_missing_or_untrusted"
            else:
                g["evidence_binding"] = "reverified_after_window_or_subject_change"
            g["inherited"] = False

    goals = list(inherited) + list(fresh_audit.get("goals") or [])
    by_sid = {str(g.get("segment_id")): g for g in goals}
    ordered: List[Dict[str, Any]] = []
    for seg in active_segs:
        sid = str(seg.get("segment_id") or seg.get("id") or "")
        g = by_sid.get(sid)
        if g is None:
            g = {
                "segment_id": sid,
                "role": seg.get("role"),
                "event_ids": list(seg.get("event_ids") or []),
                "source_media_in": seg.get("media_in"),
                "source_media_out": seg.get("media_out"),
                "media_in": seg.get("media_in"),
                "media_out": seg.get("media_out"),
                "source_video_sha256": video_sha,
                "observation_window": {
                    "media_in": seg.get("media_in"),
                    "media_out": seg.get("media_out"),
                },
                "first_live_status": "UNRESOLVED",
                "evidence_binding": "missing_audit_row",
                "inherited": False,
                "visual_verified": False,
            }
        ordered.append(g)

    # Never upgrade UNRESOLVED→VERIFIED; demote false verified claims.
    for g in ordered:
        if g.get("first_live_status") == "FIRST_LIVE_VERIFIED" and not (
            g.get("agent_auto_verified") and g.get("goal_action_verified_ok")
        ):
            g["first_live_status"] = "UNRESOLVED"
            g["demoted_false_verified"] = True

    counts = {s: 0 for s in FIRST_LIVE_STATUSES}
    for g in ordered:
        st = str(g.get("first_live_status") or "UNRESOLVED")
        if st not in counts:
            st = "UNRESOLVED"
            g["first_live_status"] = st
        counts[st] += 1

    deleted_ledger = [
        {
            "segment_id": str(s.get("segment_id") or s.get("id") or ""),
            "role": s.get("role"),
            "media_in": s.get("media_in"),
            "media_out": s.get("media_out"),
            "event_ids": list(s.get("event_ids") or []),
            "include_in_cut": False,
            "note": "excluded_from_final_goal_anchor_count",
        }
        for s in deleted_segs
    ]
    dump(dest / "deleted_goal_segments_ledger.json", {"segments": deleted_ledger})

    manifest = {
        "schema": "v3a_final_goal_evidence_manifest_v1",
        "label": label,
        "source_video": str(video),
        "source_video_sha256": video_sha,
        "n_goal_anchors": len(ordered),
        "n_deleted_goal_segments": len(deleted_ledger),
        "deleted_goal_segments": deleted_ledger,
        "status_counts": counts,
        "n_inherited": sum(1 for g in ordered if g.get("inherited")),
        "n_reverified": sum(1 for g in ordered if not g.get("inherited")),
        "prior_source_missing_records": missing_source_records,
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
            "Only include_in_cut goal-action segments counted. "
            "Historical SHA is never auto-stamped from the current video. "
            "Inheritance requires trusted prior SHA + matching EDL and observation windows "
            "+ matching goal identity (role/event_ids). "
            "FIRST_LIVE_VERIFIED additionally requires non-empty matching event_ids on both sides."
        ),
    }
    dump(dest / "final_goal_evidence_manifest.json", manifest)
    return manifest


def _parse_recovery_id_from_event(eid: str) -> Optional[str]:
    s = str(eid or "")
    m = re.match(r"^v3_goal_(goalcand_.+)$", s)
    if m:
        return m.group(1)
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
        ann = str(ch.get("annotation_id") or "")
        for e in ch.get("events") or []:
            qual = f"causal:{ann}:{e.get('event_id')}"
            if qual == str(event_id):
                return dict(ch)
    return None


def _explicit_recovery_link(
    *,
    event_ids: Sequence[str],
    recovery_by_id: Mapping[str, Mapping[str, Any]],
) -> Tuple[Optional[str], Optional[Dict[str, Any]], str]:
    """Strict: Recovery ID must appear in event_ids and exist in candidates."""
    for eid in event_ids:
        rid = _parse_recovery_id_from_event(str(eid))
        if rid and rid in recovery_by_id:
            return rid, dict(recovery_by_id[rid]), "explicit_event_id"
        # causal:ann:v3_goal_* nested
        if "v3_goal_goalcand_" in str(eid):
            m = re.search(r"(goalcand_[A-Za-z0-9_]+)", str(eid))
            if m and m.group(1) in recovery_by_id:
                rid = m.group(1)
                return rid, dict(recovery_by_id[rid]), "explicit_qualified_event_id"
    return None, None, "no_explicit_recovery_id"


def _inferred_recovery_by_pts(
    *,
    media_in: Optional[float],
    recovery_by_id: Mapping[str, Mapping[str, Any]],
    tol_sec: float = 45.0,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    if media_in is None:
        return None, None
    best = None
    best_d = None
    best_id = None
    for rid, c in recovery_by_id.items():
        action = c.get("goal_action_sec")
        if action is None:
            continue
        d = abs(float(action) - float(media_in))
        if d <= tol_sec and (best_d is None or d < best_d):
            best, best_d, best_id = dict(c), d, rid
    return best_id, best


def _explicit_chain_link(
    *,
    predicted_causal: Mapping[str, Any],
    event_ids: Sequence[str],
    recovery_id: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], str]:
    for eid in event_ids:
        ch = _chain_for_event(predicted_causal, str(eid))
        if ch is not None:
            # Chain must contain a goal-like event or verifiable source relation.
            has_goal = False
            for e in ch.get("events") or []:
                typ = e.get("type")
                en = str(e.get("type_en") or "").lower()
                if typ in {"进球", "乌龙球", "头球破门"} or en in {"goal", "own_goal", "header_goal"}:
                    has_goal = True
                    break
                if str(e.get("event_id")) == str(eid) or str(eid).endswith(str(e.get("event_id"))):
                    has_goal = True
                    break
            if has_goal or recovery_id:
                return ch, "explicit_event_in_chain"
    if recovery_id:
        for ch in predicted_causal.get("causal_chains") or []:
            if str(ch.get("goal_candidate_id") or "") == str(recovery_id):
                return dict(ch), "explicit_goal_candidate_id"
            for e in ch.get("events") or []:
                if str(e.get("event_id")) == f"v3_goal_{recovery_id}":
                    return dict(ch), "explicit_v3_goal_event"
    return None, "no_explicit_causal_chain"


def _explicit_graph_links(
    *,
    graph_nodes: Mapping[str, Mapping[str, Any]],
    segment_id: str,
    event_ids: Sequence[str],
    recovery_id: Optional[str],
    chain: Optional[Mapping[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], List[str]]:
    """Graph segment must exist; event node must link to causal/goal event when present."""
    reasons: List[str] = []
    graph_seg = graph_nodes.get(segment_id)
    if graph_seg is None:
        reasons.append("missing_story_graph_segment")
    graph_event = None
    for eid in event_ids:
        graph_event = graph_nodes.get(f"event:{eid}")
        if graph_event:
            break
    if graph_event is None and recovery_id:
        graph_event = graph_nodes.get(f"event:v3_goal_{recovery_id}")
    if graph_event is None and event_ids:
        reasons.append("missing_story_graph_event_node")
    # Segment↔event consistency when both exist.
    if graph_seg and graph_event:
        linked = str(graph_event.get("linked_from_segment") or "")
        if linked and linked != segment_id:
            reasons.append("graph_event_linked_from_other_segment")
    if chain and graph_event is None and not event_ids:
        reasons.append("chain_without_graph_event")
    return (
        dict(graph_seg) if graph_seg else None,
        dict(graph_event) if graph_event else None,
        reasons,
    )


def build_goal_lineage_report(
    *,
    edl: Any,
    predicted_causal: Mapping[str, Any],
    goal_recovery: Mapping[str, Any],
    story_graph: Optional[Mapping[str, Any]] = None,
    evidence_manifest: Optional[Mapping[str, Any]] = None,
    final_mp4: Optional[Path] = None,
) -> Dict[str, Any]:
    """Recovery → Causal → Graph → EDL → MP4 with STRICT vs INFERRED association."""
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
        if isinstance(c, dict) and c.get("candidate_id")
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
        if not _included_in_cut(seg):
            continue  # deleted goals excluded from final lineage totals

        sid = str(seg.get("segment_id") or "")
        event_ids = [str(x) for x in (seg.get("event_ids") or [])]
        tl = tl_by_sid.get(sid) or {}
        evid = evid_by_sid.get(sid) or {}
        in_final_video = bool(tl.get("has_media_window")) and sid in tl_by_sid

        recovery_id, rec, rec_how = _explicit_recovery_link(
            event_ids=event_ids, recovery_by_id=recovery_by_id
        )
        recovery_link_class = "STRICT" if recovery_id else None
        if recovery_id is None:
            inf_id, inf_rec = _inferred_recovery_by_pts(
                media_in=seg.get("media_in"), recovery_by_id=recovery_by_id
            )
            if inf_id:
                recovery_id, rec = inf_id, inf_rec
                rec_how = "inferred_nearest_pts"
                recovery_link_class = "INFERRED"

        chain, chain_how = _explicit_chain_link(
            predicted_causal=predicted_causal,
            event_ids=event_ids,
            recovery_id=recovery_id if recovery_link_class == "STRICT" else None,
        )
        chain_link_class = "STRICT" if chain is not None else None
        # If only inferred recovery, do not promote chain via that recovery id to STRICT.
        if chain is None and recovery_link_class == "INFERRED" and recovery_id:
            ch2, how2 = _explicit_chain_link(
                predicted_causal=predicted_causal,
                event_ids=event_ids,
                recovery_id=recovery_id,
            )
            if ch2 is not None:
                chain, chain_how = ch2, f"inferred_via_{how2}"
                chain_link_class = "INFERRED"

        graph_seg, graph_event, graph_reasons = _explicit_graph_links(
            graph_nodes=graph_nodes,
            segment_id=sid,
            event_ids=event_ids,
            recovery_id=recovery_id if recovery_link_class == "STRICT" else None,
            chain=chain if chain_link_class == "STRICT" else None,
        )
        graph_ok = graph_seg is not None and sid in graph_nodes
        # Event node required when event_ids present for STRICT graph completeness.
        graph_strict = graph_ok and (
            not event_ids or graph_event is not None
        ) and not any(
            r in graph_reasons for r in (
                "graph_event_linked_from_other_segment",
                "missing_story_graph_segment",
            )
        )

        # STRICT_COMPLETE: every hop explicit + in timeline.
        strict_ok = bool(
            in_final_video
            and graph_strict
            and chain_link_class == "STRICT"
            and (
                recovery_link_class == "STRICT"
                or (
                    # Strip/causal atom goals without recovery ID are OK if event→chain→graph explicit.
                    recovery_link_class is None
                    and event_ids
                    and chain is not None
                )
            )
            and seg.get("media_in") is not None
        )
        inferred_ok = (not strict_ok) and bool(
            in_final_video
            and graph_ok
            and (
                recovery_link_class == "INFERRED"
                or chain_link_class == "INFERRED"
                or (chain is not None and graph_seg is not None)
            )
        )
        if strict_ok:
            lineage_class = LINEAGE_STRICT
        elif inferred_ok:
            lineage_class = LINEAGE_INFERRED
        else:
            lineage_class = LINEAGE_UNRESOLVED

        gaps = []
        if recovery_link_class != "STRICT" and not (
            event_ids and chain_link_class == "STRICT"
        ):
            gaps.append("no_explicit_recovery_link")
        if chain_link_class != "STRICT":
            gaps.append("no_explicit_causal_chain")
        if not graph_strict:
            gaps.extend(graph_reasons or ["graph_incomplete"])
        if not in_final_video:
            gaps.append("not_in_final_mp4_timeline")
        if str(evid.get("first_live_status") or "UNRESOLVED") != "FIRST_LIVE_VERIFIED":
            gaps.append("first_live_unresolved")

        rows.append({
            "segment_id": sid,
            "role": seg.get("role"),
            "lineage_class": lineage_class,
            "recovery_candidate_id": recovery_id,
            "recovery_link": rec_how,
            "recovery_link_class": recovery_link_class,
            "score_before": (rec or {}).get("score_before"),
            "score_after": (rec or {}).get("score_after"),
            "goal_action_sec": (rec or {}).get("goal_action_sec") or seg.get("goal_anchor_t_sec"),
            "score_confirmation_sec": (rec or {}).get("score_confirmation_sec"),
            "source_media_in": seg.get("media_in"),
            "source_media_out": seg.get("media_out"),
            "predicted_causal_chain_id": (chain or {}).get("annotation_id"),
            "prediction_source": (chain or {}).get("prediction_source"),
            "causal_link": chain_how,
            "causal_link_class": chain_link_class,
            "causal_event_ids": event_ids,
            "story_graph_segment_node": (graph_seg or {}).get("id"),
            "story_graph_event_node": (graph_event or {}).get("id"),
            "story_in": tl.get("story_in"),
            "story_out": tl.get("story_out"),
            "in_final_mp4": bool(in_final_video),
            "final_mp4": str(final_mp4) if final_mp4 else None,
            "first_live_status": evid.get("first_live_status") or "UNRESOLVED",
            "evidence_binding": evid.get("evidence_binding"),
            "strict_complete": lineage_class == LINEAGE_STRICT,
            "gaps": gaps,
        })

    n_strict = sum(1 for r in rows if r["lineage_class"] == LINEAGE_STRICT)
    n_inferred = sum(1 for r in rows if r["lineage_class"] == LINEAGE_INFERRED)
    n_unresolved = sum(1 for r in rows if r["lineage_class"] == LINEAGE_UNRESOLVED)

    report = {
        "schema": "v3a_goal_lineage_report_v1",
        "n_final_goal_segments": len(rows),
        "n_strict_complete": n_strict,
        "n_inferred": n_inferred,
        "n_unresolved": n_unresolved,
        # Backward-compatible alias: only STRICT counts as structurally proven.
        "n_structurally_traced_to_mp4": n_strict,
        "n_lineage_rows": len(rows),
        "entered_predicted_causal_alone_insufficient": True,
        "nearest_pts_alone_insufficient_for_strict": True,
        "goals": rows,
        "duplicate_segment_ids": [
            sid for sid, n in (
                (s, sum(1 for r in rows if r["segment_id"] == s))
                for s in {r["segment_id"] for r in rows}
            ) if n > 1
        ],
        "note": (
            "STRICT_COMPLETE requires explicit Recovery/Causal/Graph/EDL/timeline links. "
            "Nearest-PTS recovery matches are INFERRED only and never count as STRICT."
        ),
    }
    return report


def compare_candidate_delivery_video_binding(
    *,
    delivery_manifest: Mapping[str, Any],
    candidate_manifest: Optional[Mapping[str, Any]],
    delivery_edl: Any,
    candidate_edl: Optional[Any],
) -> Dict[str, Any]:
    """Ensure candidate/delivery evidence refer to the same source video identity."""
    d_sha = delivery_manifest.get("source_video_sha256")
    c_sha = (candidate_manifest or {}).get("source_video_sha256") if candidate_manifest else None
    same_video = (candidate_manifest is None) or (d_sha and c_sha and d_sha == c_sha)

    def _goal_windows(edl: Any) -> Dict[str, Tuple[Optional[float], Optional[float]]]:
        out = {}
        for s in _edl_segments(edl):
            if not is_goal_action_segment(s) or not _included_in_cut(s):
                continue
            sid = str(s.get("segment_id") or "")
            out[sid] = (s.get("media_in"), s.get("media_out"))
        return out

    d_win = _goal_windows(delivery_edl)
    c_win = _goal_windows(candidate_edl) if candidate_edl is not None else {}
    shared = sorted(set(d_win) & set(c_win))
    changed = [
        sid for sid in shared
        if not (
            _pts_eq(d_win[sid][0], c_win[sid][0]) and _pts_eq(d_win[sid][1], c_win[sid][1])
        )
    ]
    only_cand = sorted(set(c_win) - set(d_win))
    only_del = sorted(set(d_win) - set(c_win))
    return {
        "schema": "v3a_candidate_delivery_video_binding_v1",
        "same_source_video_sha256": bool(same_video),
        "delivery_sha256": d_sha,
        "candidate_sha256": c_sha,
        "shared_goal_segments": shared,
        "window_changed_segments": changed,
        "candidate_only_goal_segments": only_cand,
        "delivery_only_goal_segments": only_del,
        "note": (
            "Candidate and delivery manifests must not share verification conclusions "
            "across changed windows; both must bind to the same source video SHA."
        ),
    }


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

    # Historical prior: pass through AS-IS. Never stamp current video SHA onto it.
    priors: List[Mapping[str, Any]] = []
    prior_source_trust: Dict[str, Any] = {
        "prior_provided": bool(prior_v3r_audit),
        "prior_has_trusted_sha": False,
        "stamped_current_sha_onto_prior": False,
    }
    if prior_v3r_audit:
        prior_sha = trusted_prior_video_sha(prior_v3r_audit)
        prior_source_trust["prior_has_trusted_sha"] = bool(prior_sha)
        prior_source_trust["prior_source_video_sha256"] = prior_sha
        # Shallow copy without mutating historical SHA fields.
        pa = json.loads(json.dumps(prior_v3r_audit))
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
    dump(dest / "final_goal_evidence_manifest.json", delivery_manifest)
    dump(dest / "prior_source_trust.json", prior_source_trust)

    candidate_manifest = None
    if candidate_edl is not None:
        candidate_manifest = bind_edl_goal_evidence(
            label="v3a_candidate",
            edl=candidate_edl,
            video=video,
            out_dir=dest / "candidate",
            events_path=events_path,
            goal_recovery=goal_recovery,
            prior_audits=priors,
            source_video_sha256=video_sha,
        )
        dump(dest / "candidate_goal_evidence_manifest.json", candidate_manifest)

    binding = compare_candidate_delivery_video_binding(
        delivery_manifest=delivery_manifest,
        candidate_manifest=candidate_manifest,
        delivery_edl=delivery_edl,
        candidate_edl=candidate_edl,
    )
    dump(dest / "candidate_delivery_video_binding.json", binding)

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
        "prior_source_trust": prior_source_trust,
        "candidate_delivery_binding": binding,
    }
