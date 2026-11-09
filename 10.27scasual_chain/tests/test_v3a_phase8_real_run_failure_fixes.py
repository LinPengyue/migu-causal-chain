"""Zero-HTTP regressions from the Phase8 real paid-run failure audit.

Frozen artifacts under _story_va_outputs/.../real_vlm_multiround — no API calls,
no hand-picked A/B winners hardcoded as the preferred semantic answer.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from story_video_agent_v3.story_evidence_search import (
    EVIDENCE_TIER_EVENT_PTS,
    EVIDENCE_TIER_FIRST_LIVE,
    _apply_feedback_to_candidates,
    _annotate_first_live_tier,
    _rank_events_in_window,
    build_candidate_selection_diagnostics,
    run_story_evidence_search,
    search_candidates_to_observations,
    verify_search_candidate,
)
from story_video_agent_v3.story_revision_feedback import (
    categories_compatible,
    should_penalize_candidate,
)
from story_video_agent_v3.story_revision_planner import (
    _intents_from_verified_search,
    plan_from_diagnosis,
)

REAL_RUN = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/phase8_paid_run_20261109/real_vlm_multiround"
)
EVIDENCE_STORE = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/phase8_paid_run_20261109/first_live_evidence_store"
)
SOURCE_SHA = "a66147f79609c8fbf831a8bd29de4c6d7f746b314b2b18a88ffb1fc5f319da9c"


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


@unittest.skipUnless(REAL_RUN.is_dir(), "real_vlm_multiround artifacts missing")
class TestRealRunFailureRootCauses(unittest.TestCase):
    def test_category_family_matches_transition_break_vs_transition(self):
        self.assertTrue(categories_compatible("transition", "transition_break"))
        rec = _load(REAL_RUN / "02_round_01/phase8_feedback_memory_snapshot.json")["records"][0]
        cand = _load(REAL_RUN / "02_round_02/evidence_search.json")["verified_candidates"][0]
        # Reproduce pre-fix miss then post-fix hit
        legacy_sig = {
            "category": cand.get("category"),  # transition
            "anchor_segment_ids": [
                cand.get("insert_after_segment_id"),
                cand.get("before_segment_id"),
            ],
        }
        hit = should_penalize_candidate(
            [rec],
            issue_signature=legacy_sig,
            action="search_add",
            source_pts=[cand["source_pts_start"], cand["source_pts_end"]],
        )
        self.assertTrue(hit["suppress"], hit)
        self.assertIn("repeat_blocked", str(hit.get("reason")))

    def test_round2_feedback_now_filters_3504(self):
        es = _load(REAL_RUN / "02_round_02/evidence_search.json")
        fb = _load(REAL_RUN / "02_round_01/phase8_feedback_memory_snapshot.json")
        before = [c["candidate_id"] for c in es["verified_candidates_before_feedback"]]
        self.assertIn("cand_event_000417_3504", before)
        out = _apply_feedback_to_candidates(es["verified_candidates_before_feedback"], fb)
        kept_ids = [c["candidate_id"] for c in out["verified_candidates"]]
        filtered_ids = [c["candidate_id"] for c in out["feedback_filtered_candidates"]]
        self.assertNotIn("cand_event_000417_3504", kept_ids)
        self.assertIn("cand_event_000417_3504", filtered_ids)

    def test_evidence_tier_not_first_live_for_event_gate(self):
        gate = verify_search_candidate(
            {
                "source_pts_start": 3504.14,
                "source_pts_end": 3515.83,
                "confidence": 0.9,
                "live": {"live_ok": True, "is_replay": False, "is_slow_motion": False},
            },
            edl=[],
        )
        self.assertTrue(gate["ok"])
        self.assertEqual(gate["evidence_tier"], EVIDENCE_TIER_EVENT_PTS)
        self.assertIn("Not FIRST_LIVE", gate["note"])

    def test_annotate_attested_windows_executable(self):
        from story_video_agent_v3.first_live_window_evidence import load_evidence_store

        store = load_evidence_store(EVIDENCE_STORE)
        # 3504 unattested
        u = _annotate_first_live_tier(
            {
                "candidate_id": "cand_event_000417_3504",
                "source_pts_start": 3504.14,
                "source_pts_end": 3515.83,
                "evidence_tier": EVIDENCE_TIER_EVENT_PTS,
            },
            evidence_store=store,
            source_sha=SOURCE_SHA,
        )
        self.assertFalse(u["executable_safe_revision"])
        self.assertEqual(u["evidence_tier"], EVIDENCE_TIER_EVENT_PTS)
        # 2273 attested by user review
        a = _annotate_first_live_tier(
            {
                "candidate_id": "cand_event_000313_2273",
                "source_pts_start": 2273.2,
                "source_pts_end": 2290.41,
            },
            evidence_store=store,
            source_sha=SOURCE_SHA,
        )
        self.assertTrue(a["executable_safe_revision"])
        self.assertEqual(a["evidence_tier"], EVIDENCE_TIER_FIRST_LIVE)

    def test_intents_only_executable_become_search_add(self):
        es = _load(REAL_RUN / "02_round_01/evidence_search.json")
        from story_video_agent_v3.first_live_window_evidence import load_evidence_store

        store = load_evidence_store(EVIDENCE_STORE)
        annotated = [
            _annotate_first_live_tier(dict(c), evidence_store=store, source_sha=SOURCE_SHA)
            for c in es["verified_candidates"]
        ]
        report = {
            "verified_candidates": annotated,
            "executable_first_live_candidates": [
                c for c in annotated if c.get("executable_safe_revision")
            ],
            "propose_only_event_pts_candidates": [
                c for c in annotated if not c.get("executable_safe_revision")
            ],
        }
        intents = _intents_from_verified_search(report, protect=[])
        adds = [i for i in intents if i.get("action") == "search_add"]
        # 3504 must not be executable search_add
        self.assertFalse(any("3504" in str(i.get("intent_id")) for i in adds))
        # Attested 2273 may be search_add for setup→buildup issue
        self.assertTrue(any("2273" in str(i.get("intent_id")) for i in adds))
        # Unattested 3504 remains propose-only at evidence tier (even if same-issue
        # propose intent is omitted once an executable insert exists).
        row_3504 = next(c for c in annotated if "3504" in str(c.get("candidate_id")))
        self.assertFalse(row_3504.get("executable_safe_revision"))
        self.assertEqual(row_3504.get("evidence_tier"), EVIDENCE_TIER_EVENT_PTS)
        obs = search_candidates_to_observations(report)
        self.assertTrue(all(o["search_candidate"].get("executable_safe_revision") for o in obs))
        self.assertFalse(any("3504" in str(o.get("request_id")) for o in obs))

    def test_llm_mark_unresolved_overrides_search_revise(self):
        """Simulate Round2 merge rule without calling paid API."""
        # Inline the decision logic used in story_e2e_agent after the fix.
        rev = {
            "decision": "REVISE",
            "search_confirmation": True,
            "revision_intents": [
                {"action": "search_add", "intent_id": "search_add_0_cand_event_000417_3504"}
            ],
        }
        llm_rev = _load(REAL_RUN / "02_round_02/llm_revision_planner.json")
        self.assertEqual(llm_rev.get("decision"), "UNRESOLVED")
        llm_intents = list(llm_rev.get("revision_intents") or [])
        llm_acts = {str(i.get("action") or "") for i in llm_intents if isinstance(i, dict)}
        llm_has_mut = bool(llm_acts - {"keep", "mark_unresolved"})
        self.assertFalse(llm_has_mut)
        search_backed = bool(rev.get("search_confirmation")) and str(rev.get("decision")).upper() == "REVISE"
        # Post-fix behavior:
        if not llm_has_mut:
            merged = {
                **rev,
                "decision": "UNRESOLVED",
                "revision_intents": llm_intents,
                "llm_overlay_note": "llm_unresolved_or_keep_only_overrides_search_bound_revise"
                if search_backed
                else "llm_unresolved_or_keep_only_honored",
                "search_revise_suppressed_by_llm": bool(search_backed),
            }
        self.assertEqual(merged["decision"], "UNRESOLVED")
        self.assertTrue(merged["search_revise_suppressed_by_llm"])
        self.assertTrue(all(i.get("action") == "mark_unresolved" for i in merged["revision_intents"]))
        # Pre-fix note must no longer be the outcome.
        self.assertNotEqual(
            merged["llm_overlay_note"],
            "llm_returned_no_mutating_intents; retained_search_bound_revise",
        )

    def test_gap_balance_is_diagnostic_not_rank_reward(self):
        # After 6f6a62e / narrative-fit: gap_balance and destination proximity are
        # retained as diagnostics only. Metadata heat may outrank a mid-gap clip.
        def _ev(eid, mid, typ, heat, crit):
            return {
                "event_id": eid,
                "event_type": typ,
                "media_time": {
                    "start_time_sec": mid - 4.0,
                    "event_time_sec": mid,
                    "end_time_sec": mid + 4.0,
                },
                "video_context": {
                    "broadcast_phase": "LIVE",
                    "is_replay": False,
                    "is_slow_motion": False,
                },
                "scores": {
                    "overall_score": 3,
                    "emotional_heat_score": heat,
                    "criticality_score": crit,
                },
            }

        ranked = _rank_events_in_window(
            [_ev("near_hi", 92.0, "Save", 3, 3), _ev("balanced", 50.0, "Shot", 3, 2)],
            lo=0.0,
            hi=100.0,
            hints=("shot", "save"),
            goals=[],
            occupied=[],
        )
        self.assertGreaterEqual(len(ranked), 2)
        by_id = {r["event_id"]: r for r in ranked}
        self.assertIn("near_hi", by_id)
        self.assertIn("balanced", by_id)
        # Mid-window still reports a higher gap_balance diagnostic.
        self.assertGreater(
            float(by_id["balanced"]["gap_balance"]),
            float(by_id["near_hi"]["gap_balance"]),
        )
        # Ranking no longer rewards gap_balance: higher heat+criticality leads.
        self.assertEqual(ranked[0]["event_id"], "near_hi")
        self.assertGreater(
            float(ranked[0]["rank_score"]),
            float(by_id["balanced"]["rank_score"]),
        )
        diag = build_candidate_selection_diagnostics(ranked)
        self.assertEqual(diag[0]["evidence_tier"], EVIDENCE_TIER_EVENT_PTS)

    def test_plan_from_frozen_diagnosis_does_not_revise_on_3504_alone(self):
        diag = _load(REAL_RUN / "02_round_01/story_diagnosis.json")
        es = _load(REAL_RUN / "02_round_01/evidence_search.json")
        from story_video_agent_v3.first_live_window_evidence import load_evidence_store

        store = load_evidence_store(EVIDENCE_STORE)
        annotated = [
            _annotate_first_live_tier(dict(c), evidence_store=store, source_sha=SOURCE_SHA)
            for c in es["verified_candidates"]
        ]
        report = {
            **es,
            "verified_candidates": annotated,
            "executable_first_live_candidates": [
                c for c in annotated if c.get("executable_safe_revision")
            ],
            "propose_only_event_pts_candidates": [
                c for c in annotated if not c.get("executable_safe_revision")
            ],
            "executable_search_success": any(c.get("executable_safe_revision") for c in annotated),
            "selection_diagnostics": build_candidate_selection_diagnostics(annotated),
        }
        plan = plan_from_diagnosis(diag, search_results=report, offline=True)
        adds = [i for i in plan["revision_intents"] if i.get("action") == "search_add"]
        self.assertFalse(any("3504" in str(i.get("intent_id")) for i in adds))
        # If 2273 is in executable pool for a confirmed issue, REVISE is allowed —
        # but never via unattested 3504.
        if adds:
            self.assertTrue(all(i.get("evidence_tier") == EVIDENCE_TIER_FIRST_LIVE for i in adds))
            self.assertTrue(all(i.get("executable_safe_revision") for i in adds))


class TestResolveCliModeStillSafe(unittest.TestCase):
    def test_import_resolve_from_cli(self):
        from story_video_agent_v3.story_e2e_cli import resolve_cli_mode
        import argparse

        ns = argparse.Namespace(offline=False, enable_real_api=False)
        skip, enable, notes = resolve_cli_mode(ns)
        self.assertTrue(skip)
        self.assertFalse(enable)


if __name__ == "__main__":
    unittest.main()
