"""Phase10-C: isolated, hypothesis-driven fullcut candidate, NEVER a release.

An exploratory edit may be worth *testing* without a confirmed existing
defect. This NEVER turns a hypothesis into a fact, alters a production EDL,
grants first-LIVE status or promotes BEST. Only existing, unprotected media
can be removed/trimmed/reordered in v1. New material remains subject to the
older independent source-PTS, live and narrative-fit gates.

No API calls. The optional renderer is injected by the unified E2E caller;
tests may inject a stub but it is always recorded as FIXTURE.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import secrets
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from .story_edl_safety import check_source_pts_monotonic
from .story_timeline import active_cut_rows

SCHEMA = "v3a_phase10c_exploratory_candidate_v1"
ACTIONS = frozenset({"drop", "trim", "reorder"})
MIN_RETAINED_SEC = 2.0
MIN_RETAINED_RATIO = 0.45


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for buf in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(buf)
    return sha.hexdigest()


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _protected(row: Mapping[str, Any]) -> bool:
    role = str(row.get("role") or "").lower()
    if row.get("is_protected") is True or row.get("goal_action_complete") is True:
        return True
    # Opening and resolution are not expendable merely because they lack goals.
    return any(token in role for token in (
        "goal", "scoreboard", "title", "opening", "ending", "wrap",
        "close", "resolution", "final", "penalty", "red_card", "var",
    ))


def _unsafe_content(row: Mapping[str, Any]) -> bool:
    if row.get("is_replay") is True:
        return True
    shot = str(row.get("shot_kind") or "").lower()
    return any(word in shot for word in ("replay", "slow_motion", "slowmo", "rebroadcast"))


def _ids(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        str(r.get("segment_id") or "")
        for r in rows if r.get("include_in_cut", True) is not False
    ]


def propose_exploratory_cut(
    *,
    baseline_edl: Sequence[Mapping[str, Any]],
    proposal: Mapping[str, Any],
    source: str,
) -> Dict[str, Any]:
    """One self-contained exploratory cut, separate from release plan.

    The LLM may pick an existing segment and describe why a shorter or
    alternative cut could improve the story. It cannot assert video facts.
    No source expansion, insert, replacement, goal manipulation or replay.
    """
    out: Dict[str, Any] = {
        "schema": SCHEMA,
        "status": "BLOCKED",
        "source": source,
        "proposal": dict(proposal) if isinstance(proposal, Mapping) else {},
        "candidate_edl": None,
        "g0_confirmed": False,
        "human_quality_improved": False,
        "release_authorized": False,
        "promote_best": False,
    }

    def blocked(reason: str) -> Dict[str, Any]:
        out["reason"] = reason
        return out

    if source not in ("REAL_LLM", "FIXTURE"):
        return blocked("unsupported_proposal_provenance")
    if not isinstance(proposal, Mapping):
        return blocked("proposal_not_object")
    action = str(proposal.get("action") or "").lower()
    if action not in ACTIONS:
        return blocked("unsupported_exploratory_action; insert/replace require independent LIVE/narrative-fit")
    target = proposal.get("target_segment_id")
    if not isinstance(target, str) or not target.strip():
        return blocked("missing_target_segment_id")
    if not isinstance(proposal.get("hypothesis"), str) or len(proposal["hypothesis"].strip()) < 12:
        return blocked("missing_substantive_story_hypothesis")
    if not isinstance(proposal.get("expected_effect"), str) or len(proposal["expected_effect"].strip()) < 8:
        return blocked("missing_expected_story_effect")
    if not isinstance(proposal.get("risk"), str) or len(proposal["risk"].strip()) < 8:
        return blocked("missing_story_tradeoff_risk")

    orig = copy.deepcopy(list(baseline_edl))
    active = active_cut_rows(orig)
    ids = _ids(orig)
    all_ids = [str(r.get("segment_id") or "") for r in orig if isinstance(r, Mapping)]
    if not ids or len(set(all_ids)) != len(all_ids) or len(set(ids)) != len(ids):
        return blocked("ambiguous_baseline_edl_segment_ids")
    if target not in ids:
        return blocked("target_not_in_active_edl")
    if any(_unsafe_content(row) for row in active):
        return blocked("existing_candidate_contains_replay_or_slow_motion")
    original_pts = check_source_pts_monotonic(orig)
    if not original_pts.get("ok"):
        return blocked("baseline_source_pts_not_monotonic")
    by_id = {str(row.get("segment_id")): row for row in orig}
    row = by_id[target]
    if _protected(row):
        return blocked("protected_story_anchor")
    if row.get("media_in") is None or row.get("media_out") is None:
        return blocked("non_media_segment_not_explorable")
    lo, hi = _number(row.get("media_in")), _number(row.get("media_out"))
    if lo is None or hi is None or lo < 0 or hi <= lo:
        return blocked("invalid_original_source_window")
    if len([r for r in active if _number(r.get("media_out")) is not None]) < 4:
        return blocked("insufficient_media_for_exploration")

    if action == "drop":
        row["include_in_cut"] = False
        row["phase10_exploratory_reason"] = proposal["hypothesis"]
    elif action == "trim":
        new_in, new_out = _number(proposal.get("media_in")), _number(proposal.get("media_out"))
        if (new_in is None or new_out is None or
                new_in + 1e-3 < lo or new_out - 1e-3 > hi or new_out <= new_in):
            return blocked("trim_must_be_inside_existing_source_window")
        kept = new_out - new_in
        if (kept < MIN_RETAINED_SEC or kept / (hi - lo) < MIN_RETAINED_RATIO or
                (abs(new_in - lo) < 1e-3 and abs(new_out - hi) < 1e-3)):
            return blocked("trim_too_aggressive_or_unchanged")
        row["media_in"], row["media_out"] = round(new_in, 3), round(new_out, 3)
        row["phase10_exploratory_trim"] = True
    else:
        before_id = str(proposal.get("insert_before_segment_id") or "")
        if not before_id or before_id not in ids or before_id == target:
            return blocked("reorder_requires_existing_distinct_before_segment")
        if _protected(by_id[before_id]):
            # Moving a non-goal segment relative to a goal would change causal
            # framing; do not allow that on an unconfirmed hypothesis.
            return blocked("reorder_anchor_protected")
        candidates = [r for r in orig if r is not row]
        before_index = next(i for i, r in enumerate(candidates)
                            if str(r.get("segment_id") or "") == before_id)
        candidates.insert(before_index, row)
        orig = candidates

    # Goal/action/score/title/ending segment existence/order/source windows
    # must remain identical to the baseline. Do not merely count goals.
    protected_before = [
        (str(r.get("segment_id")), r.get("role"), r.get("media_in"),
         r.get("media_out"), r.get("include_in_cut", True))
        for r in baseline_edl if isinstance(r, Mapping)
        and r.get("include_in_cut", True) is not False and _protected(r)
    ]
    protected_after = [
        (str(r.get("segment_id")), r.get("role"), r.get("media_in"),
         r.get("media_out"), r.get("include_in_cut", True))
        for r in orig if isinstance(r, Mapping)
        and r.get("include_in_cut", True) is not False and _protected(r)
    ]
    if protected_before != protected_after:
        return blocked("protected_story_anchor_changed")
    if not check_source_pts_monotonic(orig).get("ok"):
        return blocked("candidate_source_pts_not_monotonic")
    if orig == list(baseline_edl):
        return blocked("no_edl_delta")
    active_media = [
        r for r in active_cut_rows(orig)
        if _number(r.get("media_in")) is not None and
        _number(r.get("media_out")) is not None
    ]
    if len(active_media) < 3:
        return blocked("exploratory_cut_has_too_few_media_segments")

    out.update({
        "status": "PROPOSED_SAFETY_SCREENED",
        "reason": "bounded_existing_footage_edit_only",
        "action": action,
        "target_segment_id": target,
        "candidate_edl": orig,
        "source_pts_monotonic": True,
        "protected_anchors_preserved": True,
        "new_source_windows": False,
        "semantic_defect_confirmed": False,
        "quality_hypothesis_only": True,
        "note": (
            "Provisional edit is not G0-certified, visually verified, human "
            "preferred or authorized to release. Parent first-LIVE remains "
            "subject to independent audit."
        ),
    })
    return out


def execute_exploratory_trial(
    *,
    baseline_edl: Sequence[Mapping[str, Any]],
    proposal: Mapping[str, Any],
    source: str,
    baseline_mp4: Path,
    source_mp4: Path,
    story_plan: Mapping[str, Any],
    out_dir: Path,
    renderer: Callable[..., Mapping[str, Any]],
) -> Dict[str, Any]:
    """Render ONE full candidate and X/Y pack outside main revision/delivery.

    File integrity checks establish the presence of full MP4 artifacts only;
    fixture renders cannot become evidence that the candidate is high-quality.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    screened = propose_exploratory_cut(
        baseline_edl=baseline_edl, proposal=proposal, source=source,
    )
    candidate = screened.pop("candidate_edl", None)
    result: Dict[str, Any] = {
        **screened,
        "candidate_rendered": False,
        "blind_pair_status": "NO_CANDIDATE_PAIR",
        "formal_revision_applied": False,
        "formal_verified": False,
        "formal_improved": False,
        "automatic_best_update_allowed": False,
        "real_story_quality_verification": "NOT_EVALUATED",
    }
    if not candidate:
        _write(out_dir / "exploratory_trial.json", result)
        return result
    if not baseline_mp4.is_file() or not source_mp4.is_file():
        result.update(status="BLOCKED", reason="missing_baseline_or_source_mp4")
        _write(out_dir / "exploratory_trial.json", result)
        return result

    _write(out_dir / "proposed_candidate_edl.json", candidate)
    try:
        rendered = renderer(
            plan=story_plan,
            video=source_mp4,
            edl=candidate,
            out_dir=out_dir / "candidate_render",
        )
        path = Path(str(rendered.get("story_clean") or ""))
        if (not rendered.get("ok") or not path.is_file() or
                path.stat().st_size == 0):
            result.update(status="RENDER_FAILED", reason="renderer_did_not_produce_mp4")
            _write(out_dir / "exploratory_trial.json", result)
            return result
        # Blind folder contains ONLY anonymized X/Y videos and instructions.
        # Unblinding key is stored outside it, never returned with blind pack.
        blind = out_dir / "blind_review"
        blind.mkdir(parents=True, exist_ok=True)
        baseline_side = secrets.choice(("X", "Y"))
        candidate_side = "Y" if baseline_side == "X" else "X"
        for side, src in ((baseline_side, baseline_mp4), (candidate_side, path)):
            shutil.copy2(src, blind / f"{side}.mp4")
        _write(blind / "review_instructions.json", {
            "schema": "migu_story_blind_pair_packet_v1",
            "pair_id": out_dir.name,
            "review_goal": "Choose which FULL story is clearer, more coherent and more moving.",
            "quality_protocol": "migu_story_quality_protocol_v1",
            "ratings_required": [
                "story_completeness", "narrative_coherence",
                "material_narrative_value", "pacing_emotional_progression",
                "ending_theme_resolution", "audiovisual_quality",
            ],
            "human_review_required": True,
            "g0_independent_audit_pending": True,
            "video_labels": ["X.mp4", "Y.mp4"],
        })
        _write(out_dir / "PRIVATE_unblinding.json", {
            "schema": "migu_story_blind_allocation_v1",
            "pair_id": out_dir.name,
            "X": "baseline" if baseline_side == "X" else "candidate",
            "Y": "candidate" if baseline_side == "X" else "baseline",
            "baseline_sha256": _digest(baseline_mp4),
            "candidate_sha256": _digest(path),
            "source": source,
            "do_not_share_with_raters_until_reviews_sealed": True,
        })
        result.update({
            "status": "EXPLORATORY_RENDERED_NOT_VERIFIED",
            "candidate_rendered": True,
            "blind_pair_status": "BLIND_PAIR_READY",
            "candidate_mp4": str(path),
            "blind_review_dir": str(blind),
            "private_allocation_path": str(out_dir / "PRIVATE_unblinding.json"),
            "candidate_edl_path": str(out_dir / "proposed_candidate_edl.json"),
            "g0_confirmed": False,
            "release_authorized": False,
            "promote_best": False,
        })
    except Exception as exc:  # noqa: BLE001 - record renderer failure in sandbox
        result.update(status="RENDER_FAILED",
                      reason=f"{type(exc).__name__}:{exc}",
                      candidate_rendered=False)
    _write(out_dir / "exploratory_trial.json", result)
    return result


def _write(path: Path, data: Mapping[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
