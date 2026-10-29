"""Round 2.4 strip video audit — Qwen observation, never auto-upgrade predicted→verified."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from story_video_agent.api_provider import ApiProvider
from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.v2_phase_c1_toolbox import V2PhaseC1Toolbox
from story_video_agent.vision_provider import VisionProvider

_REPLAY = re.compile(r"\b(replay|slow[\s-]?mo|slo[\s-]?mo|回放|慢镜头)\b", re.I)
_LIVE = re.compile(r"\b(live|broadcast|直播)\b", re.I)


def _clip_window(t0: float, t1: float, *, max_span: float = 40.0) -> Dict[str, float]:
    """Use early attack context of long predicted strips (not midpoint invention)."""
    span = max(0.5, t1 - t0)
    if span <= max_span:
        return {"start": t0, "end": t1}
    # Prefer first max_span seconds (buildup toward later outcome)
    return {"start": t0, "end": t0 + max_span}


def grade_strip_observation(
    *,
    node_id: str,
    strip_meta: Dict[str, Any],
    prior_why: str,
    raw: Dict[str, Any],
    evidence_id: str,
) -> Dict[str, Any]:
    actions = (
        (raw.get("perception") or {}).get("observed_actions")
        or raw.get("observed_actions")
        or []
    )
    notes = str((raw.get("perception") or {}).get("notes") or raw.get("notes") or "")
    blob = " ".join(str(a) for a in actions) + " " + notes
    live_or = "unknown"
    if _REPLAY.search(blob):
        live_or = "replay"
    elif _LIVE.search(blob):
        live_or = "live"

    pred_first = str(strip_meta.get("first_event") or "")
    pred_last = str(strip_meta.get("last_event") or "")
    pred_cat = str(strip_meta.get("category") or strip_meta.get("predicted_category") or "")
    # Soft lexical match only — never verified
    hits = 0
    for tok in {pred_first, pred_last, pred_cat}:
        if tok and tok.replace("_", " ").lower() in blob.lower():
            hits += 1
    # generic football action presence
    actionish = bool(
        re.search(
            r"\b(shot|pass|tackle|corner|foul|save|cross|dribble|free[\s-]?kick|throw)\b",
            blob,
            re.I,
        )
    )
    matches = "partial" if hits >= 1 or actionish else "weak"
    if hits >= 2 and actionish:
        matches = "likely"

    # Narrative value heuristic from observation text (planner may override)
    narrative_value = "low"
    if re.search(r"\b(goal|celebrat|pressure|attack|chance|save|shot)\b", blob, re.I):
        narrative_value = "medium"
    if re.search(r"\b(comeback|equaliz|decisive|counter)\b", blob, re.I):
        narrative_value = "high"
    if live_or == "replay":
        narrative_value = "low"

    supports = None
    if prior_why:
        # If prior claimed pre-goal buildup but obs is replay/idle → conflict
        if live_or == "replay":
            supports = False
        elif matches == "weak" and not actionish:
            supports = False
        elif matches in {"likely", "partial"} and live_or != "replay":
            supports = True

    if live_or == "replay" or matches == "weak":
        recommendation = "drop"
    elif supports is False:
        recommendation = "replace"
    elif narrative_value == "low":
        recommendation = "drop"
    else:
        recommendation = "keep"

    suggested_beat = "buildup"
    if "equaliz" in (prior_why or "").lower() or "1-1" in (prior_why or ""):
        suggested_beat = "turning"
    if "3-1" in (prior_why or "") or "climax" in (prior_why or "").lower():
        suggested_beat = "climax"
    if "4-1" in (prior_why or "") or "final" in (prior_why or "").lower():
        suggested_beat = "resolution"

    return {
        "schema": "v2_r24_strip_observation_v1",
        "evidence_id": evidence_id,
        "node_id": node_id,
        "strip_chain_id": strip_meta.get("strip_chain_id"),
        "search_window": {
            "start": raw.get("media_start_sec"),
            "end": raw.get("media_end_sec"),
        },
        "predicted": {
            "category": pred_cat,
            "first_event": pred_first,
            "last_event": pred_last,
            "t0_sec": strip_meta.get("t0_sec"),
            "t1_sec": strip_meta.get("t1_sec"),
        },
        "prior_why": prior_why,
        "observed_actions": list(actions)[:12],
        "notes": notes,
        "live_or_replay": live_or,
        "matches_predicted_events": matches,
        "supports_prior_why": supports,
        "narrative_value": narrative_value,
        "suggested_beat": suggested_beat,
        "duplicate_of": None,
        "recommendation": recommendation,
        "verification_status": "observed_not_verified_causal",
        "summary": (
            f"{recommendation}: live_or_replay={live_or}, match={matches}, "
            f"narrative={narrative_value}, supports_prior={supports}"
        ),
        "render_ready": False,
    }


def audit_r23_strips(
    *,
    video: Path,
    strip_metas: Sequence[Dict[str, Any]],
    selection_reasons: Dict[str, str],
    api: ApiProvider,
    out_dir: Path,
    frame_budget: int = 48,
    max_span_sec: float = 36.0,
) -> Dict[str, Any]:
    """Qwen-audit the R2.3 non-goal strips. Does not mark strips verified_action."""
    out_dir = Path(out_dir)
    frames_dir = out_dir / "frames_strip_review"
    frames_dir.mkdir(parents=True, exist_ok=True)
    media = probe_video(video)
    store = FrameStore(media, out_dir=frames_dir, budget=FrameBudget(max_frames=frame_budget))
    vision = VisionProvider(api=api, force_mock=bool(api.force_mock))
    tools = V2PhaseC1Toolbox(
        duration=media.duration_sec,
        store=store,
        vision=vision,
        task_note=(
            "Audit strip candidate for story usefulness. Describe live attack actions vs replay. "
            "Cite frames when possible. Do not invent unseen goals."
        ),
    )

    reviews: List[Dict[str, Any]] = []
    for i, meta in enumerate(strip_metas):
        if store.budget.remaining <= 0:
            reviews.append(
                {
                    "node_id": meta.get("node_id"),
                    "recommendation": "unresolved",
                    "summary": "frame_budget_exhausted",
                    "verification_status": "unresolved",
                }
            )
            continue
        nid = str(meta.get("node_id"))
        t0 = float(meta.get("t0_sec") or 0)
        t1 = float(meta.get("t1_sec") or t0 + 20)
        win = _clip_window(t0, t1, max_span=max_span_sec)
        if win["end"] - win["start"] > 90:
            win["start"] = win["end"] - 90
        raw = tools.execute(
            "coarse_search",
            {"start": win["start"], "end": win["end"], "task_id": f"r24_{nid}"},
        )
        obs = grade_strip_observation(
            node_id=nid,
            strip_meta=meta,
            prior_why=selection_reasons.get(nid) or "",
            raw=raw,
            evidence_id=f"r24_review_{i}_{nid}",
        )
        # optional dense if borderline keep
        if (
            obs.get("recommendation") in {"keep", "replace"}
            and store.budget.remaining >= 8
            and (win["end"] - win["start"]) > 12
        ):
            mid = 0.5 * (win["start"] + win["end"])
            d0, d1 = max(win["start"], mid - 8), min(win["end"], mid + 8)
            raw2 = tools.execute(
                "dense_action_inspect",
                {"start": d0, "end": d1, "task_id": f"r24d_{nid}"},
            )
            obs2 = grade_strip_observation(
                node_id=nid,
                strip_meta=meta,
                prior_why=selection_reasons.get(nid) or "",
                raw=raw2,
                evidence_id=f"r24_dense_{i}_{nid}",
            )
            # Prefer denser actions list
            if len(obs2.get("observed_actions") or []) >= len(obs.get("observed_actions") or []):
                obs2["coarse_evidence_id"] = obs["evidence_id"]
                obs = obs2
        reviews.append(obs)

    # Duplicate detection by overlapping windows + similar recommendations
    for i, a in enumerate(reviews):
        for b in reviews[i + 1 :]:
            if a.get("recommendation") == "drop" or b.get("recommendation") == "drop":
                continue
            wa = a.get("search_window") or {}
            wb = b.get("search_window") or {}
            if wa.get("start") is None or wb.get("start") is None:
                continue
            ov = min(float(wa["end"]), float(wb["end"])) - max(float(wa["start"]), float(wb["start"]))
            if ov > 8.0:
                # mark later as duplicate
                b["duplicate_of"] = a.get("node_id")
                if b.get("recommendation") == "keep":
                    b["recommendation"] = "drop"
                    b["summary"] = (b.get("summary") or "") + f"; duplicate_overlap_with_{a.get('node_id')}"

    doc = {
        "schema": "v2_r24_strip_video_review_v1",
        "n_reviewed": len(reviews),
        "reviews": reviews,
        "frames_used": store.budget.used,
        "api_stats": api.stats.summary(),
        "note": "Observations support keep/drop/replace only; predicted strips are NOT verified_action",
        "render_ready": False,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "strip_video_review.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return doc
