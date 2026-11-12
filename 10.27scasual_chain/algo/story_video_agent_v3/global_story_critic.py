"""Global Story Critic — diagnose narrative from initial cut + plan + EDL + source refs.

Does NOT treat rule scores as semantic video proof. Distinguishes:
  observed | needs_video_verify | structure_inferred
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .story_timeline import (
    build_story_timeline,
    edl_rows,
    narrative_beat_coverage,
    protected_goal_segment_ids,
)

SEVERITY = ("critical", "major", "minor", "info")


def _issue(
    *,
    issue_id: str,
    story_time_range: Sequence[float],
    segment_ids: Sequence[str],
    observation: str,
    narrative_problem: str,
    severity: str,
    suggested_fix: str,
    evidence_sufficiency: str,
    category: str,
) -> Dict[str, Any]:
    assert evidence_sufficiency in (
        "observed",
        "needs_video_verify",
        "structure_inferred",
    )
    return {
        "issue_id": issue_id,
        "story_time_range": [float(story_time_range[0]), float(story_time_range[1])],
        "segment_ids": list(segment_ids),
        "observation": observation,
        "narrative_problem": narrative_problem,
        "severity": severity if severity in SEVERITY else "minor",
        "suggested_fix": suggested_fix,
        "evidence_sufficiency": evidence_sufficiency,
        "category": category,
    }


def _probe_story_video_duration(path: Optional[Path]) -> Optional[float]:
    if path is None or not path.is_file():
        return None
    try:
        import subprocess

        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except Exception:
        return None
    return None


def detect_goal_coverage_hypotheses(
    *,
    edl: Sequence[Mapping[str, Any]],
    raw_events: Sequence[Mapping[str, Any]],
    timeline: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Detect missing story goal-action *coverage* using board states, never gold.

    A score transition is an observed state change, not a located goal video.
    Even a missing action row is only a video-search hypothesis: the clock
    can lag, replay score bugs exist, and the action's first-live footage is
    unverified. No timestamps are injected into the EDL by this function.
    """
    from .goal_recovery import recover_goal_candidates

    candidates = recover_goal_candidates([
        dict(ev) for ev in raw_events if isinstance(ev, Mapping)
    ])
    timeline = timeline or build_story_timeline(edl)
    active = list(timeline.get("segments") or [])
    source_rows = [
        r for r in active if r.get("has_media_window")
    ]
    action_rows = [
        (r, original)
        for r in source_rows
        for original in edl
        if (
            original.get("include_in_cut", True)
            and str(original.get("segment_id") or "") == str(r.get("segment_id") or "")
            and "goal_action" in str(original.get("role") or "").lower()
            and original.get("is_replay") not in (True, "true", "True", 1)
        )
    ]
    seen_transitions: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    used_actions: set[str] = set()
    issues: List[Dict[str, Any]] = []
    for cand in candidates:
        if not cand.get("single_goal_increment"):
            continue
        score_before = tuple(cand.get("score_before") or [])
        score_after = tuple(cand.get("score_after") or [])
        if len(score_before) != 2 or len(score_after) != 2:
            continue
        key = (score_before, score_after)
        if key in seen_transitions:
            continue
        seen_transitions.add(key)
        try:
            confirm = float(cand["score_confirmation_sec"])
        except (TypeError, ValueError, KeyError):
            continue
        # Existing Goal Recovery uses a 180s scoreboard-lag search prior.
        # Avoid forcing an action after the board confirmation into coverage.
        lo, hi = max(0.0, confirm - 180.0), confirm - 0.5
        if hi <= lo:
            continue

        matches = []
        for row, original in action_rows:
            sid = str(row.get("segment_id") or "")
            if sid in used_actions:
                continue
            action_t = original.get("goal_anchor_t_sec")
            if action_t is None:
                # The midpoint is a *coverage* proxy, not a recovered goal PTS.
                action_t = (float(row["media_in"]) + float(row["media_out"])) / 2.0
            try:
                action_t = float(action_t)
            except (TypeError, ValueError, OverflowError):
                continue
            if lo <= action_t <= hi:
                matches.append((confirm - action_t, sid))
        if matches:
            matches.sort()
            used_actions.add(matches[0][1])
            continue

        # Bind the observation to nearby cut structure (no oracle role/PTS).
        before = None
        after = None
        for r in source_rows:
            if float(r["media_out"]) <= lo:
                before = r
            if after is None and float(r["media_in"]) >= lo:
                after = r
        # Prefer a scoreboard close to the new observed state; its exact role
        # is never taken as proof of the on-ball action.
        boards = [
            r for r in source_rows
            if "scoreboard" in str(r.get("role") or "").lower()
            and abs(float(r["media_in"]) - confirm) <= 30.0
        ]
        if boards:
            after = min(boards, key=lambda r: abs(float(r["media_in"]) - confirm))
        if after is not None:
            earlier = [
                r for r in source_rows
                if float(r["story_out"]) <= float(after["story_in"])
                and r.get("segment_id") != after.get("segment_id")
            ]
            if earlier:
                before = earlier[-1]
        segment_ids = []
        for r in (before, after):
            if r and r.get("segment_id") and r.get("segment_id") not in segment_ids:
                segment_ids.append(str(r["segment_id"]))
        story_start = float(before["story_out"]) if before is not None else 0.0
        story_end = (
            float(after["story_in"]) if after is not None
            else float(timeline.get("story_duration_sec") or story_start)
        )
        story_range = [min(story_start, story_end), max(story_start, story_end)]
        issue = _issue(
            issue_id=(
                f"goal_coverage_{score_before[0]}{score_before[1]}"
                f"_to_{score_after[0]}{score_after[1]}"
            ),
            story_time_range=story_range,
            segment_ids=segment_ids,
            observation=(
                f"Observed broadcast score transition {score_before} -> "
                f"{score_after} at score-confirmation PTS {confirm:.3f}s, "
                "but no distinct active non-replay goal_action cut covers "
                "the bounded preceding scoreboard-lag interval."
            ),
            narrative_problem=(
                "A game-state change may be missing its on-ball action in "
                "the edited story. Locate and verify original first-live "
                "source footage before proposing an EDL insertion."
            ),
            severity="major",
            suggested_fix="source_goal_action_search_then_video_verify",
            evidence_sufficiency="needs_video_verify",
            category="goal_coverage",
        )
        last_before = cand.get("last_before_score_obs_sec")
        try:
            search_lo = max(lo, float(last_before) - 30.0) if last_before is not None else lo
        except (TypeError, ValueError, OverflowError):
            search_lo = lo
        if hi - search_lo < 6.0:
            search_lo = lo
        issue.update({
            "diagnosis_status": "HYPOTHESIS_NEEDS_VIDEO",
            "story_defect_confirmed": False,
            "score_before": list(score_before),
            "score_after": list(score_after),
            "score_confirmation_sec": round(confirm, 3),
            "score_confirmation_carrier_event_id": cand.get("score_confirmation_event_id"),
            "source_search_interval": {
                "media_in": round(search_lo, 3),
                "media_out": round(hi, 3),
                "source": "last_old_score_observation_with_30s_lag_pad",
                "note": "Source search prior only, not the goal timestamp.",
            },
            "possible_action_interval": {
                "media_in": round(lo, 3),
                "media_out": round(hi, 3),
                "source": "score_recognition_bounded_180s_not_goal_action",
            },
            "score_transition_source": "raw_or_permitted_enriched_event_scoreboard",
            "action_timestamp_known": False,
            "first_live_verified": False,
            "auto_insert_authorized": False,
            "board_confirmation_is_not_action": True,
        })
        issues.append(issue)
    return issues


def structural_diagnosis(
    *,
    edl: Sequence[Mapping[str, Any]],
    story_plan: Optional[Mapping[str, Any]] = None,
    initial_story_mp4: Optional[Path] = None,
    source_video: Optional[Path] = None,
    raw_events: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Match-agnostic structural critic over timeline + plan + file existence.

    Intentionally avoids baking in match-specific narrative complaints.
    Issues that require watching the cut are marked needs_video_verify.
    """
    timeline = build_story_timeline(edl)
    segs = list(timeline.get("segments") or [])
    coverage = narrative_beat_coverage(timeline)
    issues: List[Dict[str, Any]] = []
    notes: List[str] = []

    mp4_dur = _probe_story_video_duration(initial_story_mp4)
    if initial_story_mp4 is None or not Path(initial_story_mp4).is_file():
        issues.append(
            _issue(
                issue_id="missing_initial_story_mp4",
                story_time_range=[0.0, float(timeline.get("story_duration_sec") or 0.0)],
                segment_ids=[],
                observation="Initial story MP4 path missing or not a file.",
                narrative_problem="Cannot perform global story understanding without the actual cut.",
                severity="critical",
                suggested_fix="render_or_locate_initial_story_mp4",
                evidence_sufficiency="observed",
                category="input_integrity",
            )
        )
    elif mp4_dur is not None and timeline.get("story_duration_sec"):
        delta = abs(mp4_dur - float(timeline["story_duration_sec"]))
        notes.append(
            f"story_mp4_duration={mp4_dur:.3f}s timeline_media={timeline['story_duration_sec']:.3f}s "
            f"delta={delta:.3f}s"
        )
        if delta > 8.0:
            issues.append(
                _issue(
                    issue_id="story_mp4_timeline_mismatch",
                    story_time_range=[0.0, float(timeline["story_duration_sec"])],
                    segment_ids=[s["segment_id"] for s in segs if s.get("has_media_window")],
                    observation=(
                        f"Rendered story duration ({mp4_dur:.2f}s) diverges from EDL media sum "
                        f"({timeline['story_duration_sec']:.2f}s) by {delta:.2f}s."
                    ),
                    narrative_problem="Cut/EDL correspondence uncertain; story analysis may be misaligned.",
                    severity="major",
                    suggested_fix="re_render_or_reconcile_edl",
                    evidence_sufficiency="observed",
                    category="timeline_integrity",
                )
            )

    if source_video is None or not Path(source_video).is_file():
        issues.append(
            _issue(
                issue_id="missing_source_video_ref",
                story_time_range=[0.0, 0.0],
                segment_ids=[],
                observation="Source match MP4 reference missing.",
                narrative_problem="Cannot search for replacement footage with provenance.",
                severity="critical",
                suggested_fix="provide_source_mp4",
                evidence_sufficiency="observed",
                category="input_integrity",
            )
        )

    media_segs = [s for s in segs if s.get("has_media_window")]
    if len(media_segs) < 2:
        issues.append(
            _issue(
                issue_id="insufficient_media_segments",
                story_time_range=[0.0, float(timeline.get("story_duration_sec") or 0.0)],
                segment_ids=[s["segment_id"] for s in segs],
                observation=f"Only {len(media_segs)} media-bearing cut segment(s).",
                narrative_problem="Story arc cannot be established from the cut.",
                severity="critical",
                suggested_fix="rebuild_edl_from_v3r",
                evidence_sufficiency="structure_inferred",
                category="arc_coverage",
            )
        )

    # Independent scoreboard states may reveal a missing major story action.
    # This is a hypothesis only; action location, first-live and quality remain
    # unknown until video observation. No benchmark Gold enters this path.
    if raw_events is not None:
        issues.extend(detect_goal_coverage_hypotheses(
            edl=edl, raw_events=raw_events, timeline=timeline,
        ))

    # Large source-time jumps are ordinary highlight editing. They are observations
    # for targeted video review, not evidence that a narrative bridge is missing.
    for a, b in zip(media_segs, media_segs[1:]):
        gap = float(b["media_in"]) - float(a["media_out"])
        if gap > 1200.0:  # >20 min source jump between adjacent cuts
            issues.append(
                _issue(
                    issue_id=f"large_source_jump_{a['segment_id']}_to_{b['segment_id']}",
                    story_time_range=[float(a["story_out"]) - 0.5, float(b["story_in"]) + 0.5],
                    segment_ids=[a["segment_id"], b["segment_id"]],
                    observation=(
                        f"Adjacent cuts jump {gap:.1f}s in source PTS "
                        f"({a['media_out']} → {b['media_in']}) while contiguous on story timeline."
                    ),
                    narrative_problem=(
                        "Source-time compression alone is not a story defect. Only propose "
                        "an insert if video shows specific omitted causal, emotional, or "
                        "game-state information necessary to understand the next beat."
                    ),
                    severity="info",
                    suggested_fix="verify_story_state_before_and_after;keep_if_coherent",
                    evidence_sufficiency="needs_video_verify",
                    category="transition",
                )
            )
            issues[-1]["temporal_discontinuity_only"] = True
            issues[-1]["source_gap_sec"] = round(gap, 3)
            issues[-1]["required_missing_information_evidence"] = (
                "specific_unexplained_story_state_change_observed_in_both_adjacent_cuts"
            )

    # Scoreboard-only aftermath after last goal action: structure flag for ending completeness.
    goal_idxs = [i for i, s in enumerate(media_segs) if "goal_action" in str(s.get("role") or "")]
    if goal_idxs:
        last_goal = media_segs[goal_idxs[-1]]
        after = [s for s in media_segs if float(s["story_in"]) >= float(last_goal["story_out"]) - 1e-6]
        after_roles = [str(s.get("role") or "") for s in after]
        only_scoreboard = after and all(
            "scoreboard" in r or "title" in r or "wrap" in r for r in after_roles
        )
        if only_scoreboard and sum(float(s["duration_sec"]) for s in after) < 8.0:
            issues.append(
                _issue(
                    issue_id="thin_post_climax_tail",
                    story_time_range=[
                        float(last_goal["story_out"]),
                        float(timeline.get("story_duration_sec") or last_goal["story_out"]),
                    ],
                    segment_ids=[s["segment_id"] for s in after],
                    observation=(
                        "After the final goal_action, remaining media cuts are short scoreboard/"
                        f"wrap material totaling {sum(float(s['duration_sec']) for s in after):.1f}s."
                    ),
                    narrative_problem=(
                        "Ending may feel abrupt; whether emotional closure is adequate requires "
                        "watching the cut (not assumed from structure alone)."
                    ),
                    severity="minor",
                    suggested_fix="verify_ending_or_extend_aftermath",
                    evidence_sufficiency="needs_video_verify",
                    category="ending",
                )
            )

    # --- Narrative beat order (role-family, match-agnostic) ---
    def _family(role: str) -> str:
        r = str(role or "")
        if "opponent_opening" in r or r.startswith("opening"):
            return "opening"
        if "buildup" in r or "deficit" in r or "setup" in r:
            return "development"
        if "equalizer" in r:
            return "turn"
        if "go_ahead" in r or "winner" in r or "climax" in r:
            return "climax"
        if "wrap" in r or "ending" in r or "close" in r or "aftermath" in r:
            return "ending"
        if "title" in r:
            return "title"
        if "goal_action" in r:
            return "goal"
        return "other"

    family_order = [_family(s.get("role")) for s in media_segs]
    # Development / buildup appearing after climax on the story timeline.
    climax_idxs = [i for i, f in enumerate(family_order) if f == "climax"]
    if climax_idxs:
        first_climax = climax_idxs[0]
        late_dev = [
            media_segs[i]
            for i, f in enumerate(family_order)
            if i > first_climax and f == "development"
        ]
        if late_dev:
            issues.append(
                _issue(
                    issue_id="development_after_climax",
                    story_time_range=[
                        float(media_segs[first_climax]["story_in"]),
                        float(late_dev[-1]["story_out"]),
                    ],
                    segment_ids=[s["segment_id"] for s in late_dev],
                    observation=(
                        "Development/buildup-role cuts appear after the first climax-role cut "
                        "on the finished story timeline."
                    ),
                    narrative_problem=(
                        "Story beat order may invert rising action and climax; verify whether "
                        "post-climax material is aftermath or misplaced pressure footage."
                    ),
                    severity="major",
                    suggested_fix="reorder_or_relabel_or_drop_post_climax_buildup",
                    evidence_sufficiency="structure_inferred",
                    category="narrative_order",
                )
            )

    # Turn (equalizer) before any opening/deficit setup when both exist.
    opening = next((s for s in media_segs if _family(s.get("role")) == "opening"), None)
    turn = next((s for s in media_segs if _family(s.get("role")) == "turn"), None)
    if opening and turn and float(turn["story_in"]) < float(opening["story_in"]):
        issues.append(
            _issue(
                issue_id="turn_before_opening",
                story_time_range=[float(turn["story_in"]), float(opening["story_out"])],
                segment_ids=[turn["segment_id"], opening["segment_id"]],
                observation="Turn/equalizer-role cut precedes opening-role cut on story timeline.",
                narrative_problem=(
                    "Narrative chronology may be inverted (turn before establishing opening)."
                ),
                severity="major",
                suggested_fix="reorder_story_beats",
                evidence_sufficiency="structure_inferred",
                category="narrative_order",
            )
        )

    # Scoreboard/confirm cut placed before its paired goal_action (same role stem).
    for i, s in enumerate(media_segs):
        role = str(s.get("role") or "")
        if "scoreboard" not in role:
            continue
        stem = role.replace("_scoreboard_anchor", "").replace("_scoreboard", "")
        later_action = next(
            (
                t
                for t in media_segs[i + 1 :]
                if stem and stem in str(t.get("role") or "") and "goal_action" in str(t.get("role") or "")
            ),
            None,
        )
        if later_action:
            issues.append(
                _issue(
                    issue_id=f"scoreboard_before_action_{s['segment_id']}",
                    story_time_range=[float(s["story_in"]), float(later_action["story_out"])],
                    segment_ids=[s["segment_id"], later_action["segment_id"]],
                    observation=(
                        f"Scoreboard/confirm role '{role}' appears before paired goal_action "
                        f"'{later_action.get('role')}'."
                    ),
                    narrative_problem=(
                        "Result confirmation before the action break can break causal storytelling."
                    ),
                    severity="major",
                    suggested_fix="place_action_before_scoreboard_or_drop_premature_confirm",
                    evidence_sufficiency="structure_inferred",
                    category="narrative_causality",
                )
            )

    # Buildup density between opening and turn (structure only; still needs video verify).
    if opening and turn and float(opening["story_out"]) <= float(turn["story_in"]):
        between = [
            s
            for s in media_segs
            if float(opening["story_out"]) - 1e-6
            <= float(s["story_in"])
            < float(turn["story_in"]) + 1e-6
        ]
        between_media = sum(float(s["duration_sec"]) for s in between)
        if between_media < 6.0:
            issues.append(
                _issue(
                    issue_id="sparse_pre_turn_bridge",
                    story_time_range=[float(opening["story_out"]), float(turn["story_in"])],
                    segment_ids=[s["segment_id"] for s in between],
                    observation=(
                        f"Only {between_media:.1f}s of media between opening-role cut and "
                        "turn-role cut."
                    ),
                    narrative_problem=(
                        "Rising action / pressure before the turn may be thin; confirm by watching "
                        "the story midsection — do not treat this alone as a confirmed defect."
                    ),
                    severity="minor",
                    suggested_fix="verify_buildup_or_search_bridge_footage",
                    evidence_sufficiency="needs_video_verify",
                    category="buildup",
                )
            )

    # Cross-role media duplicates: identical windows, overlap, containment.
    from .story_duplicate_audit import audit_edl_duplicates, findings_to_critic_issues

    dup_audit = audit_edl_duplicates(edl, source_mp4=None, enable_visual=False)
    for iss in findings_to_critic_issues(dup_audit, timeline=timeline):
        # Preserve preferred_drop/keep fields beyond the base _issue schema.
        base = _issue(
            issue_id=str(iss["issue_id"]),
            story_time_range=iss["story_time_range"],
            segment_ids=iss["segment_ids"],
            observation=str(iss["observation"]),
            narrative_problem=str(iss["narrative_problem"]),
            severity=str(iss["severity"]),
            suggested_fix=str(iss["suggested_fix"]),
            evidence_sufficiency=str(iss["evidence_sufficiency"]),
            category="redundancy",
        )
        for k in (
            "preferred_drop_segment_id",
            "preferred_keep_segment_id",
            "duplicate_kind",
            "duplicate_decision",
        ):
            if iss.get(k) is not None:
                base[k] = iss.get(k)
        issues.append(base)

    # Replay flags on included cuts
    for s in media_segs:
        if s.get("is_replay") in (True, "true", "True", 1):
            issues.append(
                _issue(
                    issue_id=f"replay_flagged_{s['segment_id']}",
                    story_time_range=[float(s["story_in"]), float(s["story_out"])],
                    segment_ids=[s["segment_id"]],
                    observation="EDL marks is_replay=true on an included cut.",
                    narrative_problem="Replay/slow-motion material is forbidden in delivery.",
                    severity="critical",
                    suggested_fix="drop_or_replace_with_live_action",
                    evidence_sufficiency="structure_inferred",
                    category="replay_risk",
                )
            )

    # Plan vs EDL role presence (if plan provides segments/roles)
    plan_roles: List[str] = []
    if isinstance(story_plan, Mapping):
        for key in ("segments", "beats"):
            block = story_plan.get(key)
            if isinstance(block, list):
                for item in block:
                    if isinstance(item, Mapping):
                        r = item.get("role") or item.get("label") or item.get("beat")
                        if r:
                            plan_roles.append(str(r))
                    elif isinstance(item, str):
                        plan_roles.append(item)

    protect = protected_goal_segment_ids(edl)
    return {
        "schema": "v3a_story_diagnosis_v1",
        "critic_mode": "structural_plus_file_probes",
        "inputs": {
            "initial_story_mp4": str(initial_story_mp4) if initial_story_mp4 else None,
            "source_video": str(source_video) if source_video else None,
            "story_mp4_duration_sec": mp4_dur,
            "plan_role_hints": plan_roles[:32],
        },
        "timeline": timeline,
        "coverage": coverage,
        "protected_goal_segment_ids": protect,
        "issues": issues,
        "notes": notes,
        "disclaimer": (
            "Structural/file probes are not multimodal story understanding. "
            "Issues marked needs_video_verify require layered video observation before revision."
        ),
    }


def merge_observation_into_diagnosis(
    diagnosis: Mapping[str, Any],
    observations: Mapping[str, Any],
) -> Dict[str, Any]:
    """Attach layered observe results; promote issues only when observation claims support."""
    from .semantic_story_diagnosis import apply_semantic_diagnosis_layer

    out = dict(diagnosis)
    out["layered_observations"] = observations
    obs_issues = list(observations.get("derived_issues") or [])
    merged = list(out.get("issues") or [])
    existing = {i.get("issue_id") for i in merged}
    for oi in obs_issues:
        if isinstance(oi, dict) and oi.get("issue_id") not in existing:
            merged.append(oi)
            existing.add(oi.get("issue_id"))
    out["issues"] = merged
    # Mark diagnosis validity
    has_mp4 = bool((out.get("inputs") or {}).get("initial_story_mp4"))
    out["story_diagnosis_valid"] = bool(has_mp4 and out.get("timeline"))
    out["semantic_observation_claimed"] = bool(
        observations.get("semantic_provider_used")
        and not observations.get("fixture_or_offline")
    )
    # Phase 6: structure gaps → HYPOTHESIS_NEEDS_VIDEO unless video confirms.
    out = apply_semantic_diagnosis_layer(out, observations=observations)
    return out


def write_diagnosis(path: Path, diagnosis: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(diagnosis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path

