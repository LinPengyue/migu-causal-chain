"""Live/replay splice audit for video-inferred Goals.

Rejects pairing a replay shot with a live net (or vice versa), and can rebuild
a preferred live pair from existing verification action text without new API calls
when the evidence already cites a live ball-in-net frame.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.v2_event_guided_evidence import _NET, _SHOT, _frame_id_aliases

_REPLAY = re.compile(r"\breplay\b|slo(?:w)?[- ]?mo|回放|慢镜", re.I)
_FRAME_TOKEN = re.compile(r"\b(f_?\d{3,5}(?:_\d+)?)\b", re.I)


def _clauses(text: str) -> List[str]:
    return [c.strip() for c in re.split(r"[;\n\.\|]|。|；", text or "") if c.strip()]


def _frame_time_from_verifications(
    verifications: Sequence[Dict[str, Any]],
) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for v in verifications:
        for fr in v.get("frames") or []:
            if not isinstance(fr, dict) or not fr.get("frame_id"):
                continue
            fid = str(fr["frame_id"])
            t = fr.get("actual_media_sec")
            if t is None:
                t = fr.get("requested_media_sec")
            if t is not None:
                out[fid] = float(t)
                for alias in _frame_id_aliases(fid):
                    out.setdefault(alias, float(t))
    return out


def _resolve_fid(token: str, fmap: Dict[str, float]) -> Optional[str]:
    token = str(token)
    if token in fmap:
        # Prefer longest matching store id
        cands = [k for k in fmap if token in _frame_id_aliases(k) or k == token]
        if not cands:
            return token
        return max(cands, key=len)
    for k in fmap:
        if token in _frame_id_aliases(k) or any(a == token for a in _frame_id_aliases(k)):
            return k
    return None


def extract_live_action_cites(
    verifications: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Mine shot/net frame cites; separate live vs replay clauses."""
    fmap = _frame_time_from_verifications(verifications)
    live_shots: List[Tuple[float, str, str]] = []
    live_nets: List[Tuple[float, str, str]] = []
    replay_shots: List[Tuple[float, str, str]] = []
    replay_nets: List[Tuple[float, str, str]] = []

    for v in verifications:
        eid = str(v.get("evidence_id") or "")
        acts = v.get("observed_actions") or []
        notes = ""
        ev = v.get("evidence") or {}
        if isinstance(ev.get("observed_action_sequence"), list):
            acts = list(acts) + list(ev.get("observed_action_sequence") or [])
        blob = " | ".join(str(a) for a in acts if str(a).strip())
        for ch in _clauses(blob):
            toks = _FRAME_TOKEN.findall(ch)
            if not toks:
                continue
            is_replay = bool(_REPLAY.search(ch))
            has_shot = bool(_SHOT.search(ch))
            has_net = bool(_NET.search(ch))
            for tok in toks:
                fid = _resolve_fid(tok, fmap)
                if not fid or fid not in fmap:
                    # try raw token as key
                    if tok in fmap:
                        fid = tok
                    else:
                        continue
                t = fmap[fid]
                item = (t, fid, eid)
                if has_shot and not has_net:
                    (replay_shots if is_replay else live_shots).append(item)
                if has_net:
                    (replay_nets if is_replay else live_nets).append(item)
                if has_shot and has_net and not is_replay:
                    live_shots.append(item)
                    live_nets.append(item)

    def _uniq(rows: List[Tuple[float, str, str]]) -> List[Tuple[float, str, str]]:
        seen = set()
        out = []
        for r in sorted(rows, key=lambda x: x[0]):
            if r[1] in seen:
                continue
            seen.add(r[1])
            out.append(r)
        return out

    return {
        "frame_time_map": fmap,
        "live_shots": _uniq(live_shots),
        "live_nets": _uniq(live_nets),
        "replay_shots": _uniq(replay_shots),
        "replay_nets": _uniq(replay_nets),
    }


def propose_live_shot_result_pair(
    *,
    verifications: Sequence[Dict[str, Any]],
    score_confirmation_time: Optional[float] = None,
    max_gap_sec: float = 20.0,
) -> Optional[Dict[str, Any]]:
    """Best live shot→net pair before score confirmation (no new vision calls)."""
    mined = extract_live_action_cites(verifications)
    shots = mined["live_shots"]
    nets = mined["live_nets"]
    conf = float(score_confirmation_time) if score_confirmation_time is not None else None
    best = None
    for ts, sfid, seid in shots:
        for tr, rfid, reid in nets:
            gap = tr - ts
            if gap < -0.5 or gap > max_gap_sec:
                continue
            if conf is not None and tr > conf + 5.0:
                continue
            # Prefer earlier live nets (true action before celebration/replay).
            key = (tr, gap)
            if best is None or key < (best["goal_result"]["media_sec"], best["gap_sec"]):
                best = {
                    "shot_action": {"frame_id": sfid, "media_sec": ts, "role": "shot_action"},
                    "goal_result": {"frame_id": rfid, "media_sec": tr, "role": "goal_result"},
                    "gap_sec": gap,
                    "supporting_evidence_ids": list(dict.fromkeys([seid, reid])),
                    "edit_window": {
                        "media_in": round(ts - 2.0, 3),
                        "media_out": round(tr + 3.0, 3),
                        "basis": "live_clause_rebind",
                    },
                    "live_or_replay": "live",
                    "source": "rebind_from_verification_text",
                }
    # Same-frame live "goal scored / ball enters net" clauses.
    if best is None:
        for v in verifications:
            eid = str(v.get("evidence_id") or "")
            for a in v.get("observed_actions") or []:
                ch = str(a)
                if _REPLAY.search(ch):
                    continue
                if not _NET.search(ch):
                    continue
                if not (
                    _SHOT.search(ch)
                    or re.search(r"goal\s+scored|scores?\s+a\s+goal|进球", ch, re.I)
                ):
                    continue
                toks = _FRAME_TOKEN.findall(ch)
                for tok in toks:
                    fid = _resolve_fid(tok, mined["frame_time_map"])
                    if not fid or fid not in mined["frame_time_map"]:
                        continue
                    tr = float(mined["frame_time_map"][fid])
                    if conf is not None and tr > conf + 5.0:
                        continue
                    best = {
                        "shot_action": {
                            "frame_id": fid,
                            "media_sec": tr,
                            "role": "shot_action",
                            "same_frame_as_result": True,
                        },
                        "goal_result": {
                            "frame_id": fid,
                            "media_sec": tr,
                            "role": "goal_result",
                        },
                        "gap_sec": 0.0,
                        "supporting_evidence_ids": [eid],
                        "edit_window": {
                            "media_in": round(tr - 2.0, 3),
                            "media_out": round(tr + 3.0, 3),
                            "basis": "same_frame_live_goal_clause",
                        },
                        "live_or_replay": "live",
                        "source": "same_frame_live_goal_clause",
                    }
                    break
                if best:
                    break
            if best:
                break
    if best is None and len(nets) >= 1 and not shots:
        tr, rfid, reid = nets[0]
        return {
            "goal_result": {"frame_id": rfid, "media_sec": tr, "role": "goal_result"},
            "shot_action": None,
            "gap_sec": None,
            "supporting_evidence_ids": [reid],
            "live_or_replay": "live",
            "source": "live_net_only",
            "verification_status": "candidate_needs_shot",
        }
    if best:
        best["verification_status"] = "verified_action"
        best["mined"] = {
            "n_live_shots": len(shots),
            "n_live_nets": len(nets),
            "n_replay_shots": len(mined["replay_shots"]),
            "n_replay_nets": len(mined["replay_nets"]),
        }
    return best


def audit_inferred_goal(
    *,
    inferred_event: Dict[str, Any],
    verifications: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Flag replay splice / score-path mismatch; propose live rebind when possible."""
    shot = inferred_event.get("shot_action") or {}
    result = inferred_event.get("goal_result") or {}
    ts = shot.get("media_sec")
    tr = result.get("media_sec")
    mined = extract_live_action_cites(verifications)
    issues: List[str] = []

    # Replay-frame membership
    replay_fids = {fid for _, fid, _ in mined["replay_shots"] + mined["replay_nets"]}
    live_net_fids = {fid for _, fid, _ in mined["live_nets"]}
    if shot.get("frame_id") in replay_fids:
        issues.append("shot_frame_cited_in_replay_clause")
    if result.get("frame_id") in replay_fids:
        issues.append("result_frame_cited_in_replay_clause")
    if result.get("frame_id") and result.get("frame_id") not in live_net_fids and live_net_fids:
        issues.append("result_not_in_live_net_cites_while_live_net_exists")

    # Cross-splice: shot time near replay nets while earlier live net exists
    if ts is not None and mined["live_nets"] and mined["replay_nets"]:
        live_tr = min(t for t, _, _ in mined["live_nets"])
        if float(ts) > live_tr + 15.0:
            issues.append("shot_after_earlier_live_net_suggests_replay_window")

    score_tr = (inferred_event.get("related_score_transition") or {}).get("score_confirmation_time")
    if tr is not None and score_tr is not None and float(tr) > float(score_tr) + 1.0:
        issues.append("result_after_score_confirmation")

    if ts is not None and tr is not None and float(tr) - float(ts) > 20.0:
        issues.append("shot_result_gap_exceeds_20s")

    conf = (inferred_event.get("related_score_transition") or {}).get("score_confirmation_time")
    proposal = propose_live_shot_result_pair(
        verifications=verifications, score_confirmation_time=conf
    )

    splice_risk = bool(issues)
    corrected = None
    if splice_risk and proposal and proposal.get("verification_status") == "verified_action":
        corrected = proposal
        issues.append("proposed_live_rebind")

    status = "ok"
    if splice_risk and corrected:
        status = "corrected_live_rebind"
    elif splice_risk and proposal and proposal.get("shot_action") is None:
        status = "needs_shot_localization"
    elif splice_risk:
        status = "rejected_replay_splice"
    elif inferred_event.get("video_context", {}).get("is_replay"):
        status = "rejected_pure_replay"
        issues.append("event_marked_replay")

    return {
        "schema": "v2_goal_live_replay_audit_v1",
        "inferred_event_id": inferred_event.get("inferred_event_id") or inferred_event.get("event_id"),
        "status": status,
        "issues": issues,
        "original_shot_sec": ts,
        "original_result_sec": tr,
        "mined_counts": {
            "live_shots": len(mined["live_shots"]),
            "live_nets": len(mined["live_nets"]),
            "replay_shots": len(mined["replay_shots"]),
            "replay_nets": len(mined["replay_nets"]),
        },
        "live_rebind": corrected or proposal,
        "render_ready": False,
    }


def apply_audit_correction(
    inferred_event: Dict[str, Any],
    audit: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a copy of inferred_event with live rebind times when audit corrected."""
    import copy

    out = copy.deepcopy(inferred_event)
    if audit.get("status") != "corrected_live_rebind":
        out["live_replay_audit"] = {
            "status": audit.get("status"),
            "issues": audit.get("issues"),
        }
        if audit.get("status") in {"rejected_replay_splice", "rejected_pure_replay", "needs_shot_localization"}:
            out["verification_status"] = "unresolved"
            out["as_story_node_candidate"] = False
        return out
    rb = audit.get("live_rebind") or {}
    shot = rb["shot_action"]
    result = rb["goal_result"]
    edit = rb.get("edit_window") or {}
    out["shot_action"] = shot
    out["goal_result"] = result
    out["edit_window"] = edit
    out["media_time"] = {
        "event_time_sec": float(result["media_sec"]),
        "start_time_sec": float(edit.get("media_in") or shot["media_sec"]),
        "end_time_sec": float(edit.get("media_out") or result["media_sec"]),
    }
    vc = dict(out.get("video_context") or {})
    vc["broadcast_phase"] = "LIVE"
    vc["is_replay"] = False
    out["video_context"] = vc
    out["verification_status"] = "verified_action"
    out["as_story_node_candidate"] = True
    out["live_or_replay"] = "live"
    out["notes"] = (
        str(out.get("notes") or "")
        + " | live_replay_audit corrected from verification text (no new VLM call)"
    ).strip(" |")
    out["live_replay_audit"] = {
        "status": audit.get("status"),
        "issues": audit.get("issues"),
        "rebind_source": rb.get("source"),
    }
    out["render_ready"] = False
    return out
