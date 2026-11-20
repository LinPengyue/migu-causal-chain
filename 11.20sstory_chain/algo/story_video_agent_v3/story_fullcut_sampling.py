"""Change-centered comparisons of complete story cuts under a strict frame budget.

This creates a *sampled* edit-context plus global-ending view, NOT a claim
that four frame pairs constitute a full continuous-video observation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .story_timeline import aligned_narrative_sample_plan


def _mid(seg: Mapping[str, Any]) -> float:
    return round((float(seg["story_in"]) + float(seg["story_out"])) * 0.5, 3)


def fullcut_edit_context_sample_plan(
    baseline_timeline: Mapping[str, Any],
    candidate_timeline: Mapping[str, Any],
    *,
    changed_segment_ids: Sequence[str],
    max_slots: int = 4,
) -> List[Dict[str, Any]]:
    """Include PRE, EDIT, POST and GLOBAL tail where possible.

    For an inserted segment absent from baseline, the baseline counterpart of
    EDIT is the unedited cut boundary, *not the same event*. This distinction is
    explicit in the audit metadata and vision prompt. Identity matching between
    otherwise shared EDL segments is used for PRE and POST.
    """
    b = list(baseline_timeline.get("segments") or [])
    c = list(candidate_timeline.get("segments") or [])
    bm = {str(s.get("segment_id")): s for s in b}
    cm = {str(s.get("segment_id")): s for s in c}
    # Preserve ordered change priority: caller lists newly ADDED segments
    # before incidental modified fields on older rows. Do not collapse to a
    # set and accidentally sample a metadata-only edit before the true insert.
    focus_id = next(
        (str(sid) for sid in changed_segment_ids if str(sid) in cm),
        None,
    )
    focus_index: Optional[int] = next(
        (i for i, s in enumerate(c) if str(s.get("segment_id")) == focus_id),
        None,
    ) if focus_id is not None else None
    if max_slots < 1 or focus_index is None:
        return aligned_narrative_sample_plan(
            baseline_timeline, candidate_timeline,
            changed_segment_ids=changed_segment_ids,
            max_slots=max(1, max_slots),
        )[:max_slots]

    focus = c[focus_index]
    shared_pre = next(
        (s for s in reversed(c[:focus_index]) if str(s.get("segment_id")) in bm),
        None,
    )
    shared_post = next(
        (s for s in c[focus_index + 1:] if str(s.get("segment_id")) in bm),
        None,
    )
    slots: List[Dict[str, Any]] = []

    def add_shared(slot: str, seg: Mapping[str, Any]) -> None:
        sid = str(seg.get("segment_id"))
        slots.append({
            "narrative_slot": slot,
            "reason": "same_edl_segment_context",
            "baseline_story_sec": _mid(bm[sid]),
            "candidate_story_sec": _mid(cm[sid]),
            "baseline_segment_id": sid,
            "candidate_segment_id": sid,
            "sampling_purpose": slot,
        })

    if shared_pre:
        add_shared("pre_edit", shared_pre)

    focus_id = str(focus.get("segment_id"))
    baseline_focus = bm.get(focus_id)
    if baseline_focus:
        baseline_t = _mid(baseline_focus)
        baseline_sid = focus_id
        match_kind = "modified_segment"
    elif shared_pre:
        previous = bm[str(shared_pre["segment_id"])]
        baseline_t = round(max(
            float(previous["story_in"]) + 0.05,
            float(previous["story_out"]) - 0.2,
        ), 3)
        baseline_sid = str(previous["segment_id"])
        match_kind = "counterfactual_cut_boundary_not_same_event"
    elif shared_post:
        following = bm[str(shared_post["segment_id"])]
        baseline_t = round(float(following["story_in"]) + 0.2, 3)
        baseline_sid = str(following["segment_id"])
        match_kind = "counterfactual_cut_boundary_not_same_event"
    else:
        baseline_t = round(float(baseline_timeline.get("story_duration_sec") or 0.0) * 0.5, 3)
        baseline_sid = None
        match_kind = "no_shared_anchor"
    slots.append({
        "narrative_slot": "edit_impact",
        "reason": match_kind,
        "baseline_story_sec": baseline_t,
        "candidate_story_sec": _mid(focus),
        "baseline_segment_id": baseline_sid,
        "candidate_segment_id": focus_id,
        "changed_segment_id": focus_id,
        "sampling_purpose": "edit_impact",
    })

    if shared_post:
        add_shared("post_edit", shared_post)

    # An unchanged later segment allows checking the eventual story payoff.
    shared_late = [
        s for s in reversed(c)
        if str(s.get("segment_id")) in bm
        and s.get("segment_id") not in {
            (shared_pre or {}).get("segment_id"),
            (shared_post or {}).get("segment_id"),
            focus_id,
        }
    ]
    if shared_late:
        late = shared_late[0]
        late_role = str(late.get("role") or "").lower()
        label = (
            "global_ending"
            if any(k in late_role for k in ("ending", "wrap", "close", "aftermath"))
            else "global_tail"
        )
        # An arbitrary late clip is not a proven conclusion; the screen gate
        # requires an actual ending-role observation before claiming coverage.
        add_shared(label, late)

    if len(slots) < max_slots:
        shared_first = next(
            (s for s in c if str(s.get("segment_id")) in bm),
            None,
        )
        if shared_first and shared_first["segment_id"] not in {
            x.get("candidate_segment_id") for x in slots
        }:
            add_shared("global_opening", shared_first)

    # Preserve edit evidence even when frame budget allows fewer than four
    # slots; prioritize edit itself, then adjacent causal context.
    if len(slots) > max_slots:
        chosen = sorted(
            slots,
            key=lambda s: {
                "edit_impact": 0, "pre_edit": 1, "post_edit": 2,
                "global_ending": 3, "global_tail": 4, "global_opening": 5,
            }.get(s["narrative_slot"], 5),
        )[:max_slots]
        slots = sorted(chosen, key=lambda s: {
            "global_opening": 0, "pre_edit": 1, "edit_impact": 2,
            "post_edit": 3, "global_ending": 4, "global_tail": 5,
        }.get(s["narrative_slot"], 5))
    return slots
