"""Story-First V3-A POC: event-grounded hypotheses, not verified causal claims.

Pure / zero-HTTP functions. Neither video frames nor final EDL are modified.
All source windows come from input event/EDL PTS or explicit search proposals.
Requires video semantics + FIRST_LIVE proof before any candidate can enter a cut.
Python 3.9 compatible.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .story_evidence_search import event_media_span
from .story_timeline import _num, active_cut_rows, edl_rows

SCHEMA = "story_first_hypotheses_poc_v1"
_RELATIONS = {"direct_action", "state_transition", "causal_hypothesis",
              "narrative_association", "unknown"}
_SYSTEM = """You are a long-horizon sports STORY HYPOTHESIS generator, not a commentator.
Return ONE JSON object and nothing else. Use ONLY the supplied observed events and
real event IDs. The provided V3-R story is a frozen baseline, not an answer key.
Generate up to K mutually distinguishable and FALSIFIABLE possible stories between
the two story anchors. You may return zero hypotheses if evidence is insufficient.
The full_event_inventory contains ALL events between anchors in compact form.
rich_detail_events contains a DETAIL SUBSET; never mistake it for the whole match.
For compact-only events, you may cite only provided labels and must explicitly
request video verification; do not invent extra action descriptions.
A story is a conjecture, not a fact. Do not infer player emotion, coach intention,
game tactics, possession, causal effect, replay status, or first-LIVE from mere event
ordering or labels. Do not invent video observations, times, scores, event IDs,
player names, or event relations. Long-range causal edges are UNVERIFIED hypotheses
unless source evidence proves an immediate mechanical sequence.
For EACH hypothesis include:
hypothesis_id (short string), mechanism_key (short distinct mechanism),
narrative_summary (conjectural, Chinese),
supporting_event_ids (subset of supplied event IDs),
proposed_long_range_relations (list of {source_event_id,target_event_id,
relation_type,claim}; relation_type is direct_action|state_transition|
causal_hypothesis|narrative_association|unknown),
possible_intermediate_states (list of tentative state descriptions),
uncertain_claims (list), falsification_conditions (list of specific observable tests),
observation_queries (list of {target_id,question,discriminating_signal};
target_id must belong to allowed probe IDs),
expected_story_contribution (brief text).
Do not provide source timestamps. Observation windows will be bound by CODE.
Reply JSON: {"hypotheses":[...],"insufficient_evidence_reason":"..."}.
All model statements must be treated as UNVERIFIED until source video review.
"""


def _text(value: Any, max_chars: int = 200) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        val = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        val = str(value)
    return val[:max_chars]


def _finite(x: Any) -> Optional[float]:
    v = _num(x)
    return float(v) if v is not None and math.isfinite(float(v)) else None


def _event_id(ev: Mapping[str, Any]) -> str:
    for key in ("event_id", "id", "event_uuid", "uuid"):
        v = ev.get(key)
        if v is not None and not isinstance(v, (dict, list)) and str(v).strip():
            return str(v).strip()
    return ""


def select_story_interval(
    edl_document: Any,
    *,
    from_segment_id: Optional[str] = None,
    to_segment_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Select a semantic anchor pair, not a fixed lookback window.

    Defaults to first two existing goal-action segments. Explicit IDs permit
    other templates without adding any match-specific rules.
    """
    rows = active_cut_rows(edl_rows(edl_document))
    if bool(from_segment_id) != bool(to_segment_id):
        raise ValueError("both_from_and_to_segment_ids_required")
    if from_segment_id:
        a = next((r for r in rows if str(r.get("segment_id")) == from_segment_id), None)
        b = next((r for r in rows if str(r.get("segment_id")) == to_segment_id), None)
    else:
        anchors = [r for r in rows if ("goal_action" in str(r.get("role") or "").lower()
                    or r.get("story_anchor") is True)]
        a, b = (anchors[0], anchors[1]) if len(anchors) >= 2 else (None, None)
    if a is None or b is None:
        raise ValueError("story_anchor_pair_not_found")
    lo, hi = _finite(a.get("media_out")), _finite(b.get("media_in"))
    if lo is None or hi is None or hi <= lo + 2:
        raise ValueError("invalid_anchor_pts_order")
    return {
        "from_segment_id": str(a.get("segment_id") or ""),
        "from_role": str(a.get("role") or ""),
        "to_segment_id": str(b.get("segment_id") or ""),
        "to_role": str(b.get("role") or ""),
        "source_interval_sec": [round(lo, 3), round(hi, 3)],
        "anchor_source": "existing_v3r_edl",
        "no_assumed_causality": True,
    }


def prepare_story_input(
    edl_document: Any,
    events: Sequence[Mapping[str, Any]],
    *,
    story_plan: Optional[Any] = None,
    from_segment_id: Optional[str] = None,
    to_segment_id: Optional[str] = None,
    gap_threshold_sec: float = 120.0,
    max_events: int = 240,
    max_gap_probes: int = 8,
) -> Dict[str, Any]:
    """Bind events and candidate probes to source PTS without watching video."""
    if max_events < 1 or max_events > 2000:
        raise ValueError("max_events_out_of_range")
    if not 5 <= gap_threshold_sec <= 3600:
        raise ValueError("invalid_gap_threshold")
    scope = select_story_interval(
        edl_document, from_segment_id=from_segment_id, to_segment_id=to_segment_id
    )
    lo, hi = scope["source_interval_sec"]
    occupied: List[Tuple[float, float]] = []
    for row in active_cut_rows(edl_rows(edl_document)):
        x, y = _finite(row.get("media_in")), _finite(row.get("media_out"))
        if x is not None and y is not None and y > x:
            occupied.append((x, y))

    selected: List[Dict[str, Any]] = []
    seen = set()
    unavailable_ids = 0
    timed = 0
    for ev in events:
        if not isinstance(ev, Mapping):
            continue
        eid = _event_id(ev)
        if not eid:
            unavailable_ids += 1
            continue
        span = event_media_span(ev)
        if span is None:
            continue
        a, t, b = (_finite(v) for v in span)
        if t is None or not (lo < t < hi) or a is None or b is None:
            continue
        timed += 1
        if eid in seen:
            raise ValueError("duplicate_event_id_in_scope:" + eid)
        seen.add(eid)
        vc = ev.get("video_context") if isinstance(ev.get("video_context"), Mapping) else {}
        sc = ev.get("scores") if isinstance(ev.get("scores"), Mapping) else {}
        item = {
            "event_id": eid, "source_pts_sec": round(t, 3),
            "event_type": _text(ev.get("event_type") or ev.get("event_type_zh"), 100),
            "event_type_zh": _text(ev.get("event_type_zh"), 100),
            "comment_label": _text(ev.get("comment_label"), 180),
            "description": _text(ev.get("description") or ev.get("event_description"), 180),
            "media_span_sec": [round(max(0.0, a), 3), round(b, 3)],
            "broadcast_phase_metadata": _text(vc.get("broadcast_phase"), 40),
            "is_replay_metadata": vc.get("is_replay"),
            "is_slow_motion_metadata": vc.get("is_slow_motion"),
            "scores_metadata": {k: sc.get(k) for k in (
                "overall_score", "emotional_heat_score", "criticality_score"
            ) if sc.get(k) is not None},
        }
        selected.append(item)
    selected.sort(key=lambda x: (x["source_pts_sec"], x["event_id"]))
    event_total = len(selected)
    # Preserve the FULL event index, including labels of events not chosen for
    # the rich-detail context. A story hypothesis must not mistake the
    # 240-event rich subset for all events in the anchor interval.
    full_events = list(selected)
    selected_ids = set()
    if len(selected) > max_events:
        from collections import Counter
        freq = Counter(str(e["event_type"]).lower() for e in full_events)
        n = len(full_events)
        # First protect full timeline coverage, then prioritize unusual event
        # categories and high metadata scores. These are SEARCH priors only.
        base_k = min(n, max(1, (max_events * 3) // 5))
        positions = sorted(set(min(n-1, int((j+.5)*n/base_k))
                               for j in range(base_k)))
        chosen = set(positions)
        rarity_order = sorted(range(n), key=lambda i: (
            freq[str(full_events[i]["event_type"]).lower()],
            -sum(_finite(v) or 0.0 for v in
                 full_events[i]["scores_metadata"].values()),
            full_events[i]["source_pts_sec"],
            full_events[i]["event_id"],
        ))
        for i in rarity_order:
            if len(chosen) >= max_events:
                break
            chosen.add(i)
        selected = [full_events[i] for i in sorted(chosen)]
    selected_ids = {e["event_id"] for e in selected}
    event_inventory = [
        {
            "event_id": e["event_id"],
            "source_pts_sec": e["source_pts_sec"],
            "event_type": e["event_type"],
            "comment_label": _text(e["comment_label"], 65),
            "scores_metadata": e["scores_metadata"],
            "is_rich_context": e["event_id"] in selected_ids,
            "known_replay_or_slowmo": (
                str(e.get("broadcast_phase_metadata") or "").upper() == "REPLAY"
                or e.get("is_replay_metadata") in (True, "true", "True", 1)
                or e.get("is_slow_motion_metadata") in (True, "true", "True", 1)
            ),
        }
        for e in full_events
    ]
    probes: List[Dict[str, Any]] = []
    for ev in full_events:
        # Replays may inform what an annotation refers to, but are NOT legal
        # candidate SOURCE observations under the first-broadcast constraint.
        if (str(ev.get("broadcast_phase_metadata") or "").upper() == "REPLAY"
                or ev.get("is_replay_metadata") in (True, "true", "True", 1)
                or ev.get("is_slow_motion_metadata") in (True, "true", "True", 1)):
            continue
        t = ev["source_pts_sec"]
        a, b = max(lo, t - 8), min(hi, t + 8)
        if b - a < 1:
            continue
        probes.append({
            "probe_id": "event:" + ev["event_id"], "event_id": ev["event_id"],
            "source_interval_sec": [round(a, 3), round(b, 3)],
            "origin": "real_event_pts_plus_fixed_probe_margin",
            "contains_uncertified_live_only": False,
            "overlaps_existing_edl": any(b > x and a < y for x, y in occupied),
            "requires_video_caption": True, "first_live_status": "UNRESOLVED",
            "not_a_verified_event_action": True,
        })
    # Compute actual annotation gaps using FULL event coverage, not artifacts
    # introduced by rich-context sampling.
    pts = sorted(set([lo, hi] + [x["source_pts_sec"] for x in full_events]))
    gaps = sorted(
        [(pts[i+1] - pts[i], pts[i], pts[i+1]) for i in range(len(pts)-1)
         if pts[i+1] - pts[i] >= gap_threshold_sec],
        key=lambda g: (-g[0], g[1]),
    )
    for i, (duration, a, b) in enumerate(gaps[:max_gap_probes], 1):
        midpoint = (a + b) / 2
        span = min(15.0, duration / 4.0)
        probes.append({
            "probe_id": "gap:%03d" % i, "event_id": None,
            "source_interval_sec": [round(midpoint - span, 3),
                                    round(midpoint + span, 3)],
            "origin": "unobserved_gap_midpoint_search_proposal",
            "gap_bounds_sec": [round(a, 3), round(b, 3)],
            "contains_uncertified_live_only": False,
            "overlaps_existing_edl": any(midpoint + span > x and midpoint - span < y
                                          for x, y in occupied),
            "requires_video_caption": True, "first_live_status": "UNRESOLVED",
            "not_a_verified_event_action": True,
        })
    # Include the whole plan as context only up to a bounded serialization size.
    plan_summary = _text(story_plan, 9000) if story_plan is not None else ""
    return {
        "schema": SCHEMA, "scope": scope, "events": selected,
        "event_inventory": event_inventory,
        "probes": probes, "story_plan_reference": plan_summary,
        "rich_context_selection": (
            "all_events" if event_total <= max_events
            else "temporal_coverage_plus_type_rarity_metadata_priors_v1"
        ),
        "data_tier": "HUMAN_ATOM_ENRICHED_DEV",
        "counts": {
            "supplied_event_rows": len(events),
            "events_with_missing_ids": unavailable_ids,
            "timed_events_inside_scope": timed,
            "distinct_events_inside_scope": event_total,
            "events_in_llm_context": len(selected),
            "events_in_full_inventory": len(event_inventory),
            "events_dropped_by_context_cap": event_total - len(selected),
            "events_not_in_rich_detail_context": event_total - len(selected),
            "events_omitted_entirely_from_prompt": 0,
            "observation_probes": len(probes),
            "gap_probes": min(len(gaps), max_gap_probes),
        },
        "observation_only": True, "edl_modified": False,
        "verified_long_range_causal_links": 0, "first_live_certified": False,
    }


def model_messages(prepared: Mapping[str, Any], max_hypotheses: int = 5) -> List[Dict[str, str]]:
    if not 1 <= max_hypotheses <= 5:
        raise ValueError("max_hypotheses_must_be_1_to_5")
    data = {
        "K": max_hypotheses, "story_scope": prepared["scope"],
        "frozen_story_plan": prepared["story_plan_reference"],
        # Full coverage: all real IDs and their labels. Rich context is a
        # documented subset, never the only universe of potential explanations.
        "full_event_inventory": prepared["event_inventory"],
        "rich_detail_events": [
            {
                "event_id": e["event_id"],
                "source_pts_sec": e["source_pts_sec"],
                "event_type": e["event_type"],
                "comment_label": e["comment_label"],
                "description": e["description"],
                "broadcast_phase_metadata": e["broadcast_phase_metadata"],
                "scores_metadata": e["scores_metadata"],
            }
            for e in prepared["events"]
        ],
        "observation_probe_contract": {
            "event_probe_format": "event:<event_id>",
            "event_id_must_be_in_full_inventory": True,
            "event_probes_must_not_be_known_replay_or_slowmo": True,
            "event_probe_time_bounds_computed_by_code": True,
            "gap_probes": [
                {"probe_id": p["probe_id"],
                 "source_interval_sec": p["source_interval_sec"]}
                for p in prepared["probes"]
                if str(p["probe_id"]).startswith("gap:")
            ],
        },
    }
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": json.dumps(data, ensure_ascii=False, separators=(",", ":"))},
    ]


def parse_hypotheses(
    model_json: Mapping[str, Any],
    prepared: Mapping[str, Any],
    *,
    max_hypotheses: int = 5,
) -> Dict[str, Any]:
    """Validate model claims and block invented IDs or source PTS."""
    if not isinstance(model_json, Mapping):
        raise ValueError("model_output_not_json_object")
    rows = model_json.get("hypotheses")
    if not isinstance(rows, list) or len(rows) > max_hypotheses:
        raise ValueError("invalid_hypothesis_count")
    allowed_events = {
        x["event_id"] for x in prepared.get("event_inventory", prepared["events"])
    }
    allowed_probes = {x["probe_id"] for x in prepared["probes"]}
    forbidden_time_fields = {
        "source_pts_start", "source_pts_end", "source_pts_sec",
        "media_in", "media_out", "media_pts", "timestamp", "start_sec", "end_sec"
    }
    accepted, rejected, mechanisms, hids = [], [], set(), set()
    for idx, item in enumerate(rows):
        if not isinstance(item, Mapping):
            rejected.append({"index": idx, "reason": "non_object"})
            continue
        hid = _text(item.get("hypothesis_id"), 80)
        mech = _text(item.get("mechanism_key"), 120).strip().lower()
        if not hid or not mech or hid in hids or mech in mechanisms:
            rejected.append({"index": idx, "reason": "empty_or_duplicate_identity"})
            continue
        ids = item.get("supporting_event_ids")
        relations = item.get("proposed_long_range_relations")
        queries = item.get("observation_queries")
        falsifiers = item.get("falsification_conditions")
        if (not isinstance(ids, list) or not ids or
                not isinstance(relations, list) or not isinstance(queries, list) or
                not isinstance(falsifiers, list) or not falsifiers):
            rejected.append({"index": idx, "reason": "missing_evidence_or_test"})
            continue
        ids = [str(v) for v in ids]
        if any(x not in allowed_events for x in ids):
            rejected.append({"index": idx, "reason": "unrecognized_event_id"})
            continue
        valid = True
        for rel in relations:
            if (not isinstance(rel, Mapping) or
                    str(rel.get("source_event_id") or "") not in allowed_events or
                    str(rel.get("target_event_id") or "") not in allowed_events or
                    rel.get("relation_type") not in _RELATIONS or
                    any(key in rel for key in forbidden_time_fields)):
                valid = False
                break
        if not valid:
            rejected.append({"index": idx, "reason": "unverifiable_relation"})
            continue
        for q in queries:
            if (not isinstance(q, Mapping) or
                    str(q.get("target_id") or "") not in allowed_probes or
                    any(key in q for key in forbidden_time_fields)):
                valid = False
                break
        if not valid:
            rejected.append({"index": idx, "reason": "invalid_observation_probe"})
            continue
        if any(key in item for key in forbidden_time_fields):
            rejected.append({"index": idx, "reason": "model_invented_time_field"})
            continue
        accepted.append({
            "hypothesis_id": hid, "mechanism_key": mech,
            "narrative_summary": _text(item.get("narrative_summary"), 600),
            "supporting_event_ids": ids,
            "proposed_long_range_relations": [
                {"source_event_id": str(r["source_event_id"]),
                 "target_event_id": str(r["target_event_id"]),
                 "relation_type": str(r["relation_type"]),
                 "claim": _text(r.get("claim"), 300),
                 "evidence_status": "UNVERIFIED_MODEL_HYPOTHESIS"} for r in relations
            ],
            "possible_intermediate_states": [_text(v, 200) for v in
                (item.get("possible_intermediate_states") or [])][:10],
            "uncertain_claims": [_text(v, 200) for v in
                (item.get("uncertain_claims") or [])][:10],
            "falsification_conditions": [_text(v, 300) for v in falsifiers][:10],
            "observation_queries": [
                {"target_id": str(q["target_id"]), "question": _text(q.get("question"), 250),
                 "discriminating_signal": _text(q.get("discriminating_signal"), 250)}
                for q in queries
            ][:12],
            "expected_story_contribution": _text(item.get("expected_story_contribution"), 350),
            "causal_claim_validated": False, "video_observed": False,
            "eligible_for_edl": False,
        })
        mechanisms.add(mech)
        hids.add(hid)
    return {
        "schema": SCHEMA, "hypotheses": accepted, "rejected": rejected,
        "insufficient_evidence_reason": _text(
            model_json.get("insufficient_evidence_reason"), 400
        ),
        "status": "UNVERIFIED_HYPOTHESES" if accepted else "NO_VALID_HYPOTHESES",
        "truth_claim": False, "edl_modified": False,
        "first_live_certified": False,
    }


def build_observation_plan(
    prepared: Mapping[str, Any], validated: Mapping[str, Any]
) -> Dict[str, Any]:
    lookup = {x["probe_id"]: x for x in prepared["probes"]}
    targets: List[Dict[str, Any]] = []
    seen = set()
    for h in validated.get("hypotheses") or []:
        for query in h["observation_queries"]:
            pid = query["target_id"]
            key = (h["hypothesis_id"], pid)
            if key in seen:
                continue
            seen.add(key)
            p = lookup[pid]
            targets.append({
                "hypothesis_id": h["hypothesis_id"], "probe_id": pid,
                "source_interval_sec": p["source_interval_sec"],
                "origin": p["origin"], "question": query["question"],
                "discriminating_signal": query["discriminating_signal"],
                "first_live_status": "UNRESOLVED",
                "video_caption_status": "NOT_OBSERVED",
                "automatic_edl_insert": False,
            })
    return {
        "schema": SCHEMA, "targets": targets,
        "all_searchable_probes": list(lookup.values()),
        "observation_is_not_causal_proof": True,
        "first_live_certified": False, "edl_modified": False,
    }


def evidence_matrix(prepared: Mapping[str, Any], validated: Mapping[str, Any]) -> Dict[str, Any]:
    ev = {
        x["event_id"]: x
        for x in prepared.get("event_inventory", prepared["events"])
    }
    ev.update({x["event_id"]: x for x in prepared["events"]})
    out = []
    for h in validated.get("hypotheses") or []:
        out.append({
            "hypothesis_id": h["hypothesis_id"],
            "supporting_events": [ev[x] for x in h["supporting_event_ids"]],
            "relation_status": "HYPOTHESIZED_NOT_VERIFIED",
            "contradicting_video_evidence": [],
            "causal_mechanism_verified": False,
            "observation_target_count": len(h["observation_queries"]),
        })
    return {"schema": SCHEMA, "rows": out, "video_evidence_inspected": False}


def baseline_candidates(prepared: Mapping[str, Any]) -> Dict[str, Any]:
    # Keep the event-only control complete; the story prompt receives full
    # coverage too, even when rich details are capped.
    events = list(prepared.get("event_inventory", prepared["events"]))
    chronology = [e["event_id"] for e in events]
    def score(e: Mapping[str, Any]) -> float:
        sc = e.get("scores_metadata") or {}
        return sum((_finite(sc.get(x)) or 0.0) for x in
                   ("overall_score", "emotional_heat_score", "criticality_score"))
    ranked = sorted(
        events,
        key=lambda e: (-score(e), e["source_pts_sec"], e["event_id"]),
    )
    return {
        "schema": SCHEMA,
        "chronological_event_ids": chronology,
        "importance_ranked_event_ids": [e["event_id"] for e in ranked],
        "note": "Deterministic event-only references, NOT equal-budget LLM baselines or quality scores.",
    }
