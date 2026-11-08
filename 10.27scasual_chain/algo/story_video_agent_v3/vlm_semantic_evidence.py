"""Convert VLM cut observations into structured semantic evidence for Critic.

Distinguishes:
  MODEL_CLAIMED  — model asserts a defect without checkable frame/clip refs
  EVIDENCE_SUPPORTED — asserts defect AND cites sent frame_ids that check out

CONFIRMED_STORY_DEFECT requires EVIDENCE_SUPPORTED for the original issue_id.
Model self-reported confidence alone never confirms.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple


def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _collect_frame_ids(obj: Any) -> List[str]:
    found: List[str] = []
    if isinstance(obj, dict):
        for k in ("frame_id", "frame", "ref", "id"):
            v = obj.get(k)
            if v is not None and str(v).strip():
                found.append(str(v).strip())
        for refs in (obj.get("evidence_refs"), obj.get("frame_refs"), obj.get("clip_refs")):
            for r in _as_list(refs):
                found.extend(_collect_frame_ids(r))
        for v in obj.values():
            if isinstance(v, (dict, list)):
                found.extend(_collect_frame_ids(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(_collect_frame_ids(v))
    elif isinstance(obj, str):
        # tolerate bare ids in prose
        for m in re.finditer(r"\b(?:baseline_|candidate_|f|frame_|para_|global_|local_)[\w.\-]+\b", obj):
            found.append(m.group(0))
    # unique preserve order
    out: List[str] = []
    for f in found:
        if f not in out:
            out.append(f)
    return out


def _checkable_citations(cited: Sequence[str], sent: Set[str]) -> Tuple[List[str], List[str]]:
    ok = [c for c in cited if c in sent]
    missing = [c for c in cited if c not in sent]
    return ok, missing


def normalize_semantic_evidence_item(
    raw: Mapping[str, Any],
    *,
    sent_frame_ids: Sequence[str],
    observation_scope: Optional[Mapping[str, Any]] = None,
    default_issue_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Normalize one evidence row; never invent issue_id or quality labels."""
    sent = {str(x) for x in sent_frame_ids}
    issue_id = raw.get("issue_id") or default_issue_id
    observed_fact = (
        raw.get("observed_fact")
        or raw.get("observation")
        or raw.get("observed_visuals")
        or raw.get("observed_evidence")
    )
    hypothesis = (
        raw.get("defect_hypothesis")
        or raw.get("narrative_problem")
        or raw.get("hypothesis")
    )
    story_time = raw.get("story_time") or raw.get("story_time_range")
    cited = _collect_frame_ids(raw)
    # also scan observed_fact text
    if isinstance(observed_fact, str):
        for tok in sent:
            if tok in observed_fact and tok not in cited:
                cited.append(tok)
    ok_cites, missing = _checkable_citations(cited, sent)
    model_claims_defect = bool(
        raw.get("claims_story_defect")
        or str(raw.get("evidence_sufficiency") or "").lower() == "observed"
        or str(raw.get("status") or "").lower() in ("confirmed", "defect", "broken")
        or (hypothesis and observed_fact)
    )
    # Supports original issue only if model explicitly ties to issue_id and cites frames.
    supports_original = bool(
        issue_id
        and model_claims_defect
        and len(ok_cites) >= 2
        and not missing
        and bool(observed_fact)
        and bool(hypothesis)
    )
    if supports_original:
        claim_status = "EVIDENCE_SUPPORTED"
        evidence_sufficiency = "observed"
    elif model_claims_defect:
        claim_status = "MODEL_CLAIMED"
        evidence_sufficiency = "needs_video_verify"
    else:
        claim_status = "INCONCLUSIVE"
        evidence_sufficiency = str(raw.get("evidence_sufficiency") or "needs_video_verify")

    try:
        conf = float(raw.get("confidence")) if raw.get("confidence") is not None else None
    except (TypeError, ValueError):
        conf = None

    return {
        "schema": "v3a_semantic_evidence_item_v1",
        "issue_id": issue_id,
        "story_time": story_time,
        "frame_refs": ok_cites,
        "frame_refs_missing": missing,
        "observed_fact": observed_fact,
        "defect_hypothesis": hypothesis,
        "confidence_model_reported": conf,
        "observation_scope": observation_scope
        or raw.get("observation_scope")
        or {
            "method": "ordered_multi_frame",
            "claims_full_video_watch": False,
        },
        "claim_status": claim_status,
        "supports_original_issue": supports_original,
        "evidence_sufficiency": evidence_sufficiency,
        "note": (
            "Model confidence alone never confirms. EVIDENCE_SUPPORTED requires "
            "≥2 checkable sent frame_ids + observed_fact + defect_hypothesis + issue_id."
        ),
    }


def vlm_critic_to_observation_updates(
    vlm_critic: Mapping[str, Any],
    *,
    sent_frame_ids: Sequence[str],
    hypothesis_issues: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build derived_issues + confirmed_issue_ids for observe/diagnosis merge."""
    parsed = vlm_critic.get("parsed") if isinstance(vlm_critic.get("parsed"), dict) else {}
    scope = {
        "method": vlm_critic.get("observation_method") or "ordered_multi_frame_vlm",
        "claims_full_video_watch": bool(vlm_critic.get("claims_full_video_watch")),
        "sent_frame_ids": list(sent_frame_ids),
        "limitation": (
            "Sparse/dense still frames in story-time order — NOT native continuous "
            "video bitstream watch unless explicitly provided."
        ),
    }
    raw_items: List[Mapping[str, Any]] = []
    for key in ("semantic_evidence", "evidence_items", "derived_issues"):
        for it in _as_list(parsed.get(key) if parsed else None) or _as_list(
            vlm_critic.get(key)
        ):
            if isinstance(it, dict):
                raw_items.append(it)
    # Also map confirmed_issues list of ids/objects into claimed rows without auto-support.
    for it in _as_list(parsed.get("confirmed_issues")):
        if isinstance(it, str):
            raw_items.append(
                {
                    "issue_id": it,
                    "claims_story_defect": True,
                    "observation": f"model_listed_confirmed_issue:{it}",
                    "narrative_problem": "model_claim_without_inline_evidence",
                    "evidence_sufficiency": "needs_video_verify",
                }
            )
        elif isinstance(it, dict):
            raw_items.append({**it, "claims_story_defect": True})

    hyp_ids = {
        str(i.get("issue_id"))
        for i in (hypothesis_issues or [])
        if isinstance(i, dict) and i.get("issue_id")
    }
    evidence_items = [
        normalize_semantic_evidence_item(
            it,
            sent_frame_ids=sent_frame_ids,
            observation_scope=scope,
        )
        for it in raw_items
    ]
    # Drop empty shells
    evidence_items = [
        e
        for e in evidence_items
        if e.get("issue_id") or e.get("observed_fact") or e.get("defect_hypothesis")
    ]

    derived_issues: List[Dict[str, Any]] = []
    confirmed_ids: List[str] = []
    for e in evidence_items:
        iid = e.get("issue_id")
        if not iid:
            continue
        # Prefer upgrading known hypotheses; still allow new issue_ids with evidence.
        row = {
            "issue_id": iid,
            "category": "transition" if "jump" in str(iid) or "bridge" in str(iid) else "buildup",
            "severity": "major" if e["claim_status"] == "EVIDENCE_SUPPORTED" else "minor",
            "observation": e.get("observed_fact"),
            "observed_evidence": e.get("observed_fact"),
            "narrative_problem": e.get("defect_hypothesis"),
            "missing_information": e.get("defect_hypothesis"),
            "causal_explanation": e.get("defect_hypothesis"),
            "story_time_range": e.get("story_time")
            if isinstance(e.get("story_time"), list)
            else [0.0, 0.0],
            "segment_ids": [],
            "evidence_sufficiency": e["evidence_sufficiency"],
            "evidence_refs": [{"frame_id": f, "note": "vlm_semantic_evidence"} for f in e["frame_refs"]],
            "claim_status": e["claim_status"],
            "suggested_fix": "revise_with_evidence"
            if e["claim_status"] == "EVIDENCE_SUPPORTED"
            else "needs_more_video_evidence",
            "confidence": e.get("confidence_model_reported"),
            "observation_scope": e.get("observation_scope"),
        }
        derived_issues.append(row)
        if e["supports_original_issue"] and e["claim_status"] == "EVIDENCE_SUPPORTED":
            # Only confirm if it addresses a known hypothesis OR is explicitly evidenced.
            if (not hyp_ids) or (str(iid) in hyp_ids) or True:
                # Always allow evidence-supported confirmation; hyp filter is informational.
                if str(iid) not in confirmed_ids:
                    confirmed_ids.append(str(iid))

    return {
        "schema": "v3a_vlm_observation_updates_v1",
        "semantic_evidence": evidence_items,
        "derived_issues": derived_issues,
        "confirmed_issue_ids": confirmed_ids,
        "model_claimed_only_ids": [
            str(e["issue_id"])
            for e in evidence_items
            if e.get("issue_id") and e.get("claim_status") == "MODEL_CLAIMED"
        ],
        "observation_scope": scope,
        "stats": {
            "n_evidence": len(evidence_items),
            "n_evidence_supported": sum(
                1 for e in evidence_items if e["claim_status"] == "EVIDENCE_SUPPORTED"
            ),
            "n_model_claimed": sum(
                1 for e in evidence_items if e["claim_status"] == "MODEL_CLAIMED"
            ),
            "n_confirmed_issue_ids": len(confirmed_ids),
        },
    }


def extract_dense_frames_for_issue(
    *,
    story_mp4: Path,
    edl: Sequence[Mapping[str, Any]],
    issue: Mapping[str, Any],
    out_dir: Path,
    fps: float = 1.0,
    max_frames: int = 10,
    pad_sec: float = 1.0,
) -> Dict[str, Any]:
    """Dense timestamped stills over the issue story window (not full-video watch)."""
    from story_video_agent.frames import FrameBudget, FrameStore
    from story_video_agent.media import probe_video
    from .story_timeline import build_story_timeline

    out_dir.mkdir(parents=True, exist_ok=True)
    tl = build_story_timeline(edl)
    dur = float(tl.get("story_duration_sec") or 0.0)
    rng = list(issue.get("story_time_range") or [0.0, min(8.0, dur)])
    lo = max(0.05, float(rng[0]) - pad_sec)
    hi = min(max(lo + 0.5, float(rng[1]) + pad_sec), max(0.1, dur - 0.05))
    if not story_mp4.is_file() or dur <= 0:
        return {
            "ok": False,
            "error": "missing_story_mp4_or_duration",
            "frames": [],
            "sent_frame_ids": [],
            "claims_full_video_watch": False,
        }
    n = min(max_frames, max(3, int((hi - lo) * fps) + 1))
    times = [lo + (hi - lo) * i / max(1, n - 1) for i in range(n)]
    store = FrameStore(
        probe_video(story_mp4),
        out_dir=out_dir / "dense_frames",
        budget=FrameBudget(max_frames=max_frames + 2),
    )
    frames: List[Dict[str, Any]] = []
    for i, t in enumerate(times):
        rec = store.extract_at(float(t), gap_id=f"dense_{issue.get('issue_id')}", tool="phase7_dense")
        d = rec.to_dict()
        fid = f"story_{issue.get('issue_id')}_t{t:.2f}".replace(".", "p")
        d["frame_id"] = fid
        d["story_sec"] = round(t, 3)
        d["path"] = d.get("path")
        frames.append(d)
    usable = [f for f in frames if f.get("path") and Path(f["path"]).is_file()]
    return {
        "ok": len(usable) >= 3,
        "issue_id": issue.get("issue_id"),
        "story_time_range": [round(lo, 3), round(hi, 3)],
        "sample_times_story_sec": [round(t, 3) for t in times],
        "frames": usable,
        "sent_frame_ids": [str(f["frame_id"]) for f in usable],
        "observation_method": "dense_ordered_multi_frame_issue_window",
        "claims_full_video_watch": False,
        "fps_target": fps,
        "note": (
            "Dense still frames in story-time order around the hypothesized defect. "
            "Not a native continuous-video API ingest."
        ),
    }
