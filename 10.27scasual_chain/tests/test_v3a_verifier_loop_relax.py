"""Loop retain vs release gate: Verifier serves Agent revision, not every-round delivery."""
from __future__ import annotations

import unittest

from story_video_agent_v3.quality_audit import evaluate as quality_evaluate
from story_video_agent_v3.self_revise_agent import (
    apply_candidate_revision,
    composite_quality_score,
    decide_accept,
    decide_release,
    expand_windows_from_anchor,
    validate_verifier_output,
)


def _fr_like():
    story = {"match_id": "fr_syn", "title": "FR", "protagonist": "left"}
    plan = {
        "match_id": "fr_syn",
        "story_tier": "story",
        "story_scope": {
            "selected_arc": {
                "behind_start": {"t_sec": 1535.65, "score": "0:1"},
                "equalizer": {"t_sec": 2513.29, "score": "1:1"},
                "go_ahead": {"t_sec": 2904.31, "score": "2:1"},
            }
        },
        "missing_evidence": ["missing_live_goal_action:opponent_opening"],
    }
    edl = [
        {"segment_id": "seg_title", "role": "story_title", "media_in": 0.0, "media_out": 3.0,
         "include_in_cut": True, "shot_kind": "title_card"},
        {"segment_id": "seg_equalizer_goal_action", "role": "equalizer_goal_action",
         "media_in": 2398.0, "media_out": 2420.0, "include_in_cut": True, "is_replay": False},
        {"segment_id": "seg_go_ahead_goal_action", "role": "go_ahead_goal_action",
         "media_in": 2714.0, "media_out": 2736.0, "include_in_cut": True, "is_replay": False},
    ]
    return story, plan, edl


def _abc_complete():
    story = {"match_id": "abc"}
    plan = {
        "match_id": "abc", "story_tier": "story",
        "story_scope": {"selected_arc": {
            "behind_start": {"t_sec": 50, "score": "0:1"},
            "equalizer": {"t_sec": 110, "score": "1:1"},
            "go_ahead": {"t_sec": 210, "score": "2:1"},
        }},
    }
    edl = [
        {"segment_id": "seg_title", "role": "story_title", "media_in": 0, "media_out": 3,
         "include_in_cut": True, "shot_kind": "title_card"},
        {"segment_id": "seg_opponent_opening_goal_action", "role": "opponent_opening_goal_action",
         "media_in": 40, "media_out": 60, "include_in_cut": True, "is_replay": False},
        {"segment_id": "seg_filler", "role": "buildup_misc", "media_in": 10, "media_out": 20,
         "include_in_cut": True, "shot_kind": "broll"},
        {"segment_id": "seg_equalizer_goal_action", "role": "equalizer_goal_action",
         "media_in": 100, "media_out": 120, "include_in_cut": True, "is_replay": False},
        {"segment_id": "seg_go_ahead_goal_action", "role": "go_ahead_goal_action",
         "media_in": 200, "media_out": 220, "include_in_cut": True, "is_replay": False},
    ]
    return story, plan, edl


def _ok_verifier(**dims):
    base = {
        "story_element_coverage": {"status": "unchanged", "summary": "s", "evidence_refs": [{"ref": "r"}]},
        "narrative_coherence": {"status": "unchanged", "summary": "s", "evidence_refs": []},
        "image_content_quality": {"status": "unchanged", "summary": "s", "evidence_refs": []},
    }
    base.update(dims)
    return {
        "ok": True,
        "validated": validate_verifier_output({
            "issues": [],
            "dimensions": base,
            "evidence_of_improvement": [{"claim": "c", "evidence_refs": [{"ref": "x"}]}],
            "hard_vetoes": [],
            "quality_delta_vs_baseline": "local",
        }),
    }


class PartialImprovementLoopTests(unittest.TestCase):
    def test_p0_not_cleared_but_coverage_up_can_loop_retain(self):
        """FR-like: still missing something scored as feedback P0, but local improve retained."""
        story, plan, edl = _fr_like()
        # Simulate partial: add a non-goal setup segment that does not clear opening P0,
        # but soft-drop nothing — use coverage via a provisional opening that stays pending.
        # Instead: baseline missing opening (P0=1); candidate still missing opening but we
        # drop nothing — use a synthetic audit where cand_p0 still > 0 but reduced? 
        # Real path: bind opening → P0 clears. For partial: keep missing opening, improve
        # coherence via drop of a filler that we inject into FR baseline.
        edl_b = list(edl) + [{
            "segment_id": "seg_filler", "role": "buildup_misc", "media_in": 10, "media_out": 20,
            "include_in_cut": True, "shot_kind": "broll",
        }]
        cand, meta = apply_candidate_revision(
            edl_b,
            [{"intent_id": "i", "action": "drop", "target_segment_id": "seg_filler",
              "rationale": "irrelevant", "evidence_refs": [{"ref": "obs"}]}],
            [{"ok": True, "issue_id": "i", "vlm": {"visible_content": "crowd"},
              "frames": [{"actual_media_sec": 15.0}]}],
        )
        base_audit = quality_evaluate(story, plan, edl_b)
        cand_audit = quality_evaluate(story, plan, cand)
        self.assertGreaterEqual(
            sum(1 for f in cand_audit["hard_gate_findings"] if f["severity"] == "P0"), 1
        )
        verifier = _ok_verifier(
            narrative_coherence={
                "status": "improved", "summary": "dropped filler",
                "evidence_refs": [{"ref": "obs"}],
            }
        )
        d = decide_accept(
            baseline_audit=base_audit, candidate_audit=cand_audit,
            verifier=verifier, revision_meta=meta,
            baseline_edl=edl_b, candidate_edl=cand, mode="loop",
        )
        self.assertTrue(d["accept"], d["reasons"])
        self.assertTrue(d["loop_retain"])
        self.assertIn(d["path"], ("quality_improvement", "partial_improvement"))
        self.assertFalse(d["release_eligible"])
        # Remaining missing opening is feedback, not loop stop
        self.assertTrue(d["candidate_p0"] >= 1)

    def test_abc_narrative_improve_retained(self):
        story, plan, edl = _abc_complete()
        cand, meta = apply_candidate_revision(
            edl,
            [{"intent_id": "i", "action": "drop", "target_segment_id": "seg_filler",
              "rationale": "irrelevant broll", "evidence_refs": [{"ref": "obs1"}]}],
            [{"ok": True, "issue_id": "i", "vlm": {"visible_content": "crowd only"},
              "frames": [{"actual_media_sec": 15.0}]}],
        )
        base_audit = quality_evaluate(story, plan, edl)
        cand_audit = quality_evaluate(story, plan, cand)
        self.assertEqual(base_audit["hard_gate_findings"], [])
        verifier = _ok_verifier(
            narrative_coherence={
                "status": "improved", "summary": "cleaner",
                "evidence_refs": [{"ref": "obs1"}],
            }
        )
        d = decide_accept(
            baseline_audit=base_audit, candidate_audit=cand_audit,
            verifier=verifier, revision_meta=meta,
            baseline_edl=edl, candidate_edl=cand,
        )
        self.assertTrue(d["accept"])
        self.assertEqual(d["path"], "quality_improvement")


class ApiDegradeAndUnknownTests(unittest.TestCase):
    def test_api_502_rule_improve_still_loop_retains(self):
        story, plan, edl = _abc_complete()
        cand, meta = apply_candidate_revision(
            edl,
            [{"intent_id": "i", "action": "drop", "target_segment_id": "seg_filler",
              "rationale": "x", "evidence_refs": [{"ref": "r"}]}],
            [{"ok": True, "frames": [{"actual_media_sec": 15.0}]}],
        )
        base_audit = quality_evaluate(story, plan, edl)
        cand_audit = quality_evaluate(story, plan, cand)
        # Force structural signal: coverage same; rely on soft edit + eoi absent;
        # with API down, dim_improved false — need structural or soft+something.
        # Drop filler alone may not change coverage/coherence proxies. Inject
        # slightly better coverage via fake dimension scores on audits.
        base_audit = dict(base_audit)
        cand_audit = dict(cand_audit)
        base_audit["dimensions"] = {
            "story_element_coverage": {"score": 90.0},
            "story_coherence": {"score": 90.0},
        }
        cand_audit["dimensions"] = {
            "story_element_coverage": {"score": 90.0},
            "story_coherence": {"score": 100.0},
        }
        d = decide_accept(
            baseline_audit=base_audit, candidate_audit=cand_audit,
            verifier={"ok": False, "provider_mode": "degraded", "error": "502",
                      "validated": {"dimensions": {}, "hard_vetoes": [],
                                    "evidence_of_improvement": []}},
            revision_meta=meta,
            baseline_edl=edl, candidate_edl=cand,
            semantic_verification_status="NOT_EVALUATED",
        )
        self.assertTrue(d["accept"], d["reasons"])
        self.assertIn("api_verifier_degraded_rule_track_active", d["reasons"])
        self.assertFalse(d["release_eligible"])

    def test_unknown_not_zero_or_round_fail(self):
        scores = composite_quality_score(
            {"dimensions": {
                "story_element_coverage": {"score": 80},
                "story_coherence": {"score": 90},
            }},
            verifier_validated={"dimensions": {
                "image_content_quality": {"status": "NOT_EVALUATED", "score": None},
            }},
        )
        self.assertIsNotNone(scores["composite"])
        self.assertGreater(scores["composite"], 0)
        self.assertIn("image_content_quality", scores["unknown_dimensions"])
        # NOT_EVALUATED must not drag average to 0
        self.assertGreaterEqual(scores["composite"], 80.0)

    def test_api_fail_without_improvement_still_rejects(self):
        d = decide_accept(
            baseline_audit={"hard_gate_findings": [],
                            "dimensions": {"story_element_coverage": {"score": 100},
                                           "story_coherence": {"score": 100}}},
            candidate_audit={"hard_gate_findings": [],
                             "dimensions": {"story_element_coverage": {"score": 100},
                                            "story_coherence": {"score": 100}}},
            verifier={"ok": False, "provider_mode": "degraded", "error": "502",
                      "validated": {"hard_vetoes": [], "dimensions": {},
                                    "evidence_of_improvement": []}},
            revision_meta={"applied": [{"status": "applied", "action": "drop",
                                        "segment_id": "seg_filler"}]},
            semantic_verification_status="NOT_EVALUATED",
        )
        self.assertFalse(d["accept"])
        self.assertIn("api_verifier_degraded_rule_track_active", d["reasons"])


class SevereAndReleaseTests(unittest.TestCase):
    def test_confirmed_replay_still_rejected(self):
        d = decide_accept(
            baseline_audit={"hard_gate_findings": [], "dimensions": {
                "story_element_coverage": {"score": 100}, "story_coherence": {"score": 100}}},
            candidate_audit={"hard_gate_findings": [
                {"kind": "replay_as_primary", "severity": "P0", "target": "eq"}],
                "dimensions": {
                    "story_element_coverage": {"score": 100}, "story_coherence": {"score": 100}}},
            verifier=_ok_verifier(),
            revision_meta={"applied": [{"status": "applied", "action": "drop", "segment_id": "x"}]},
        )
        self.assertFalse(d["accept"])
        self.assertTrue(any("severe" in r or "replay" in r for r in d["reasons"]))

    def test_hard_veto_still_rejected(self):
        d = decide_accept(
            baseline_audit={"hard_gate_findings": [], "dimensions": {
                "story_element_coverage": {"score": 100}, "story_coherence": {"score": 100}}},
            candidate_audit={"hard_gate_findings": [], "dimensions": {
                "story_element_coverage": {"score": 100}, "story_coherence": {"score": 100}}},
            verifier={"ok": True, "validated": {
                "dimensions": {}, "evidence_of_improvement": [],
                "hard_vetoes": [{"kind": "replay_as_first_live"}],
            }},
            revision_meta={"applied": [{"status": "applied", "action": "drop", "segment_id": "x"}]},
        )
        self.assertFalse(d["accept"])
        self.assertIn("verifier_hard_veto", d["reasons"])

    def test_pending_goal_loop_retain_but_not_release(self):
        story, plan, edl = _fr_like()
        wins = expand_windows_from_anchor(
            {"kind": "T01_selected_arc_score_node", "t_sec": 1535.65}, video_duration=7305.0,
        )
        frames = []
        for i, t in enumerate([1480.0, 1488.0, 1496.0, 1504.0]):
            frames.append({
                "frame_id": f"f_{i}", "requested_media_sec": t, "actual_media_sec": t + 0.02,
                "pts_status": "pts", "path": f"/tmp/f{i}.jpg",
            })
        obs = {
            "request_id": "t0", "issue_id": "d0", "anchor_id": "score_node:behind_start",
            "ok": True, "provider_mode": "offline_fixture",
            "window": {"start": 1475.65, "end": 1505.65}, "frames": frames,
            "allowed_windows": wins, "fact_verified": False, "observation_only": True,
            "vlm": {
                "visible_content": "shot and net", "observed_shot": True, "observed_net": True,
                "live_or_replay": "live", "supports_bound_segment": True,
                "candidate_goal_action_span": {"start": 1480.0, "end": 1502.0},
                "fact_verified": False, "observation_only": True,
            },
        }
        cand, meta = apply_candidate_revision(
            edl,
            [{"intent_id": "i0", "action": "search_add", "issue_id": "d0",
              "role": "opponent_opening_goal_action", "anchor_id": "score_node:behind_start"}],
            [obs],
            trusted_windows_by_anchor={"score_node:behind_start": wins},
            score_anchor_by_anchor_id={"score_node:behind_start": 1535.65},
        )
        base_audit = quality_evaluate(story, plan, edl)
        cand_audit = quality_evaluate(story, plan, cand)
        d = decide_accept(
            baseline_audit=base_audit, candidate_audit=cand_audit,
            verifier={"ok": False, "validated": {"hard_vetoes": [], "dimensions": {},
                                                 "evidence_of_improvement": []}},
            revision_meta=meta, baseline_edl=edl, candidate_edl=cand,
            semantic_verification_status="NOT_EVALUATED",
        )
        self.assertTrue(d["accept"], d["reasons"])
        self.assertEqual(d["path"], "loop_pending_verification")
        self.assertTrue(d["pending_verification"])
        self.assertFalse(d["release_eligible"])

        rel = decide_release(
            baseline_audit=base_audit, candidate_audit=cand_audit,
            verifier={"ok": False, "validated": {"hard_vetoes": [], "dimensions": {}}},
            revision_meta=meta, candidate_edl=cand,
            semantic_verification_status="NOT_EVALUATED",
        )
        self.assertFalse(rel["release_eligible"])
        self.assertTrue(any("unverified" in r or "semantic" in r for r in rel["reasons"]))


if __name__ == "__main__":
    unittest.main()
