"""Synthetic regression tests for V3-A Agent loop gaps (no paid HTTP)."""
from __future__ import annotations

import unittest

from story_video_agent_v3.quality_audit import evaluate as quality_evaluate
from story_video_agent_v3.self_revise_agent import (
    apply_candidate_revision,
    authorize_bound_segment,
    build_trusted_anchors,
    call_llm_verifier,
    decide_accept,
    expand_windows_from_anchor,
    parse_next_search_request,
    select_followup_windows,
    validate_verifier_output,
)


def _fr_like_plan_edl():
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
        {"segment_id": "seg_deficit_scoreboard", "role": "deficit_scoreboard_anchor",
         "media_in": 1534.65, "media_out": 1538.15, "include_in_cut": True,
         "shot_kind": "scoreboard_anchor"},
        {"segment_id": "seg_equalizer_goal_action", "role": "equalizer_goal_action",
         "media_in": 2398.0, "media_out": 2420.0, "include_in_cut": True,
         "is_replay": False, "event_ids": ["e_eq"]},
        {"segment_id": "seg_go_ahead_goal_action", "role": "go_ahead_goal_action",
         "media_in": 2714.0, "media_out": 2736.0, "include_in_cut": True,
         "is_replay": False, "event_ids": ["e_ga"]},
    ]
    return story, plan, edl


def _good_goal_obs(*, start=1475.65, end=1505.65, issue_id="d0"):
    """Synthetic observation with real PTS + structured VLM support (not first-LIVE verified)."""
    frames = []
    for i, t in enumerate([1480.0, 1488.0, 1496.0, 1504.0]):
        frames.append({
            "frame_id": f"f_{i}_{int(t*1000)}",
            "requested_media_sec": t,
            "actual_media_sec": t + 0.02,
            "pts_status": "pts",
            "path": f"/tmp/fake_{i}.jpg",
        })
    return {
        "request_id": "tool_w0",
        "issue_id": issue_id,
        "anchor_id": "score_node:behind_start",
        "ok": True,
        "provider_mode": "offline_fixture",
        "window": {"start": start, "end": end},
        "frames": frames,
        "allowed_windows": [{"start": start, "end": end}],
        "fact_verified": False,
        "observation_only": True,
        "vlm": {
            "visible_content": "Shot toward goal then ball in net; live broadcast angle.",
            "observed_shot": True,
            "observed_net": True,
            "live_or_replay": "live",
            "supports_bound_segment": True,
            "candidate_goal_action_span": {"start": 1480.0, "end": 1502.0},
            "scoreboard_only": False,
            "fact_verified": False,
            "observation_only": True,
            "next_search_request": None,
        },
    }


def _negative_00_obs(*, start=1355.65, end=1385.65, issue_id="d0", next_idx=1):
    frames = [{
        "frame_id": "f0",
        "requested_media_sec": 1360.0,
        "actual_media_sec": 1360.05,
        "pts_status": "pts",
        "path": "/tmp/f0.jpg",
    }]
    return {
        "request_id": "tool_w_neg",
        "issue_id": issue_id,
        "anchor_id": "score_node:behind_start",
        "ok": True,
        "provider_mode": "offline_fixture",
        "window": {"start": start, "end": end},
        "frames": frames,
        "allowed_windows": [
            {"start": 1355.65, "end": 1385.65},
            {"start": 1385.65, "end": 1415.65},
            {"start": 1475.65, "end": 1505.65},
        ],
        "fact_verified": False,
        "observation_only": True,
        "vlm": {
            "visible_content": "Scoreboard France 0-0 Australia; open play, no goal action.",
            "observed_shot": False,
            "observed_net": False,
            "scoreboard_only": True,
            "supports_bound_segment": False,
            "fact_verified": False,
            "observation_only": True,
            "next_search_request": {"window_index": next_idx, "reason": "no_goal_in_this_window_try_later"},
        },
    }


class EvidenceBindingTests(unittest.TestCase):
    def test_fr_bound_evidence_writes_candidate_opening_edl(self):
        story, plan, edl = _fr_like_plan_edl()
        anchors = build_trusted_anchors(plan, edl)
        score = next(a for a in anchors if a["anchor_id"] == "score_node:behind_start")
        wins = expand_windows_from_anchor(score, video_duration=7305.0)
        obs = _good_goal_obs()
        obs["allowed_windows"] = wins
        # Ensure good span sits inside some trusted window
        self.assertTrue(any(w["start"] <= 1480 <= w["end"] for w in wins))
        cand, meta = apply_candidate_revision(
            edl,
            [{
                "intent_id": "i0", "action": "search_add", "issue_id": "d0",
                "role": "opponent_opening_goal_action",
                "anchor_id": "score_node:behind_start",
            }],
            [obs],
            trusted_windows_by_anchor={"score_node:behind_start": wins},
            score_anchor_by_anchor_id={"score_node:behind_start": 1535.65},
        )
        self.assertEqual(meta["evidence_bound_count"], 1)
        roles = [r.get("role") for r in cand if r.get("include_in_cut", True)]
        self.assertIn("opponent_opening_goal_action", roles)
        opening = next(r for r in cand if r.get("role") == "opponent_opening_goal_action")
        self.assertEqual(opening.get("first_live_status"), "NOT_VERIFIED")
        self.assertFalse(opening.get("agent_auto_verified"))
        audit = quality_evaluate(story, plan, cand)
        self.assertEqual(sum(1 for f in audit["hard_gate_findings"] if f["severity"] == "P0"), 0)

    def test_fr_no_reliable_evidence_keeps_p0(self):
        story, plan, edl = _fr_like_plan_edl()
        anchors = build_trusted_anchors(plan, edl)
        score = next(a for a in anchors if a["anchor_id"] == "score_node:behind_start")
        wins = expand_windows_from_anchor(score, video_duration=7305.0)
        obs = _negative_00_obs()
        cand, meta = apply_candidate_revision(
            edl,
            [{
                "intent_id": "i0", "action": "search_add", "issue_id": "d0",
                "role": "opponent_opening_goal_action",
                "anchor_id": "score_node:behind_start",
            }],
            [obs],
            trusted_windows_by_anchor={"score_node:behind_start": wins},
            score_anchor_by_anchor_id={"score_node:behind_start": 1535.65},
        )
        self.assertEqual(meta["evidence_bound_count"], 0)
        self.assertEqual(meta["pending_count"], 1)
        audit = quality_evaluate(story, plan, cand)
        self.assertGreaterEqual(sum(1 for f in audit["hard_gate_findings"] if f["severity"] == "P0"), 1)

    def test_scoreboard_time_cannot_bind_as_goal_action(self):
        frames = [{
            "frame_id": "f", "actual_media_sec": 1535.7, "requested_media_sec": 1535.7,
            "pts_status": "pts",
        }]
        auth = authorize_bound_segment(
            media_in=1534.65, media_out=1538.15,
            role="opponent_opening_goal_action",
            frames=frames,
            vlm={"supports_bound_segment": True, "observed_shot": True, "observed_net": True,
                 "fact_verified": False, "observation_only": True},
            trusted_windows=[{"start": 1530.0, "end": 1560.0}],
            score_anchor_sec=1535.65,
        )
        self.assertFalse(auth["allow"])
        self.assertTrue(any("score_confirmation" in d for d in auth["denies"]))

    def test_replay_or_fact_verified_overclaim_rejected(self):
        frames = [{"frame_id": "f", "actual_media_sec": 1490.0, "pts_status": "pts"}]
        auth = authorize_bound_segment(
            media_in=1480.0, media_out=1500.0, role="opponent_opening_goal_action",
            frames=frames,
            vlm={"supports_bound_segment": True, "live_or_replay": "replay",
                 "fact_verified": False, "observation_only": True},
            trusted_windows=[{"start": 1475.65, "end": 1505.65}],
            score_anchor_sec=1535.65,
        )
        self.assertFalse(auth["allow"])
        auth2 = authorize_bound_segment(
            media_in=1480.0, media_out=1500.0, role="opponent_opening_goal_action",
            frames=frames,
            vlm={"supports_bound_segment": True, "observed_shot": True, "observed_net": True,
                 "fact_verified": True, "observation_only": True},
            trusted_windows=[{"start": 1475.65, "end": 1505.65}],
            score_anchor_sec=1535.65,
        )
        self.assertFalse(auth2["allow"])


class AcceptPathTests(unittest.TestCase):
    def test_abc_quality_improvement_without_p0_can_accept(self):
        baseline_edl = [
            {"segment_id": "seg_title", "role": "story_title", "media_in": 0, "media_out": 3,
             "include_in_cut": True, "shot_kind": "title_card"},
            {"segment_id": "seg_filler", "role": "buildup_misc", "media_in": 10, "media_out": 20,
             "include_in_cut": True, "shot_kind": "broll"},
            {"segment_id": "seg_equalizer_goal_action", "role": "equalizer_goal_action",
             "media_in": 100, "media_out": 120, "include_in_cut": True, "is_replay": False},
            {"segment_id": "seg_go_ahead_goal_action", "role": "go_ahead_goal_action",
             "media_in": 200, "media_out": 220, "include_in_cut": True, "is_replay": False},
            {"segment_id": "seg_opponent_opening_goal_action", "role": "opponent_opening_goal_action",
             "media_in": 40, "media_out": 60, "include_in_cut": True, "is_replay": False},
        ]
        plan = {
            "match_id": "abc", "story_tier": "story",
            "story_scope": {"selected_arc": {
                "behind_start": {"t_sec": 50, "score": "0:1"},
                "equalizer": {"t_sec": 110, "score": "1:1"},
                "go_ahead": {"t_sec": 210, "score": "2:1"},
            }},
        }
        story = {"match_id": "abc"}
        cand_edl, meta = apply_candidate_revision(
            baseline_edl,
            [{"intent_id": "i", "action": "drop", "target_segment_id": "seg_filler",
              "rationale": "irrelevant broll", "evidence_refs": [{"kind": "vlm", "ref": "obs1"}]}],
            [{"ok": True, "issue_id": "i", "vlm": {"visible_content": "crowd only"},
              "frames": [{"actual_media_sec": 15.0}]}],
        )
        base_audit = quality_evaluate(story, plan, baseline_edl)
        cand_audit = quality_evaluate(story, plan, cand_edl)
        self.assertEqual(base_audit["hard_gate_findings"], [])
        self.assertEqual(cand_audit["hard_gate_findings"], [])
        # Coherence may be unchanged; provide verifier structured evidence
        verifier = {
            "ok": True,
            "validated": validate_verifier_output({
                "issues": [],
                "dimensions": {
                    "story_element_coverage": {
                        "status": "unchanged", "summary": "still covers three goals",
                        "evidence_refs": [{"ref": "edl_roles"}],
                    },
                    "narrative_coherence": {
                        "status": "improved", "summary": "removed irrelevant broll",
                        "evidence_refs": [{"ref": "obs1"}, {"ref": "drop:seg_filler"}],
                    },
                    "image_content_quality": {
                        "status": "unchanged", "summary": "n/a", "evidence_refs": [],
                    },
                },
                "evidence_of_improvement": [{
                    "claim": "dropped irrelevant buildup_misc",
                    "evidence_refs": [{"ref": "obs1"}],
                }],
                "hard_vetoes": [],
                "quality_delta_vs_baseline": "cleaner narrative",
            }),
        }
        # Force structural coherence equal; rely on dim_improved + eoi
        d = decide_accept(
            baseline_audit=base_audit,
            candidate_audit=cand_audit,
            verifier=verifier,
            revision_meta=meta,
            baseline_edl=baseline_edl,
            candidate_edl=cand_edl,
        )
        self.assertTrue(d["accept"])
        self.assertEqual(d["path"], "quality_improvement")

    def test_bad_model_suggestion_rejected_or_rolled_back(self):
        story, plan, edl = _fr_like_plan_edl()
        wins = expand_windows_from_anchor(
            {"kind": "T01_selected_arc_score_node", "t_sec": 1535.65},
            video_duration=7305.0,
        )
        # Bad: invents free time far outside trusted union via fake obs frames
        bad_obs = {
            "request_id": "bad",
            "issue_id": "d0",
            "ok": True,
            "window": {"start": 10.0, "end": 40.0},
            "frames": [{"frame_id": "f", "actual_media_sec": 20.0, "pts_status": "pts"}],
            "allowed_windows": wins,
            "vlm": {
                "supports_bound_segment": True,
                "observed_shot": True,
                "observed_net": True,
                "fact_verified": True,  # overclaim
                "observation_only": True,
                "candidate_goal_action_span": {"start": 20.0, "end": 35.0},
            },
        }
        cand, meta = apply_candidate_revision(
            edl,
            [{"intent_id": "i0", "action": "search_add", "issue_id": "d0",
              "role": "opponent_opening_goal_action", "anchor_id": "score_node:behind_start"}],
            [bad_obs],
            trusted_windows_by_anchor={"score_node:behind_start": wins},
            score_anchor_by_anchor_id={"score_node:behind_start": 1535.65},
        )
        self.assertEqual(meta["evidence_bound_count"], 0)
        audit = quality_evaluate(story, plan, cand)
        self.assertTrue(any(f["severity"] == "P0" for f in audit["hard_gate_findings"]))

    def test_verifier_failure_never_counts_as_success(self):
        d = decide_accept(
            baseline_audit={"hard_gate_findings": [],
                            "dimensions": {"story_element_coverage": {"score": 100},
                                           "story_coherence": {"score": 100}}},
            candidate_audit={"hard_gate_findings": [],
                             "dimensions": {"story_element_coverage": {"score": 100},
                                            "story_coherence": {"score": 100}}},
            verifier={"ok": False, "provider_mode": "degraded", "error": "502",
                      "rule_fallback_success": False},
            revision_meta={"applied": [{"status": "applied", "action": "drop", "segment_id": "seg_filler"}]},
            semantic_verification_status="NOT_EVALUATED",
        )
        self.assertFalse(d["accept"])
        self.assertTrue(any("verifier_failed" in r or "degraded" in r for r in d["reasons"]))


class MultiWindowFeedbackTests(unittest.TestCase):
    def test_followup_changes_window_after_negative_observation(self):
        allowed = [
            {"start": 1355.65, "end": 1385.65},
            {"start": 1385.65, "end": 1415.65},
            {"start": 1475.65, "end": 1505.65},
        ]
        neg = _negative_00_obs(next_idx=2)
        follow, log = select_followup_windows(
            allowed_windows=allowed, observed=[neg], max_followups=2,
        )
        self.assertTrue(follow)
        self.assertNotEqual(follow[0]["start"], neg["window"]["start"])
        self.assertAlmostEqual(follow[0]["start"], 1475.65)
        self.assertTrue(any(x.get("scheduled") for x in log))
        # Local negative must not be treated as match-level absence: we still schedule
        self.assertTrue(any(x.get("selection", "").startswith("allowed") or x.get("scheduled") for x in log))

    def test_free_timestamp_next_search_rejected_or_snapped(self):
        allowed = [{"start": 1355.65, "end": 1385.65}, {"start": 1385.65, "end": 1415.65}]
        out = parse_next_search_request(
            {"start": 9000.0, "end": 9030.0, "reason": "invented"},
            allowed_windows=allowed,
            prior_window=allowed[0],
        )
        self.assertTrue(out.get("rejected"))

    def test_p0_repair_accept_path(self):
        story, plan, edl = _fr_like_plan_edl()
        wins = expand_windows_from_anchor(
            {"kind": "T01_selected_arc_score_node", "t_sec": 1535.65}, video_duration=7305.0,
        )
        obs = _good_goal_obs()
        obs["allowed_windows"] = wins
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
        verifier = {
            "ok": True,
            "validated": validate_verifier_output({
                "issues": [],
                "dimensions": {
                    "story_element_coverage": {
                        "status": "improved", "summary": "opening bound",
                        "evidence_refs": [{"ref": "obs"}],
                    },
                    "narrative_coherence": {"status": "improved", "summary": "arc complete",
                                            "evidence_refs": [{"ref": "audit"}]},
                    "image_content_quality": {"status": "unknown", "summary": "", "evidence_refs": []},
                },
                "evidence_of_improvement": [{"claim": "added opening from PTS", "evidence_refs": [{"ref": "f0"}]}],
                "hard_vetoes": [],
            }),
        }
        d = decide_accept(
            baseline_audit=base_audit, candidate_audit=cand_audit,
            verifier=verifier, revision_meta=meta,
            baseline_edl=edl, candidate_edl=cand,
        )
        self.assertTrue(d["accept"])
        self.assertEqual(d["path"], "p0_repair")


class VerifierSchemaTests(unittest.TestCase):
    def test_dimensions_required_and_retry_helper_keeps_failure_honest(self):
        v = validate_verifier_output({
            "issues": [{"issue_id": "a", "severity": "P1", "dimension": "narrative_coherence",
                        "problem": "x", "evidence_refs": []}],
            "dimensions": {
                "story_element_coverage": {"status": "unchanged", "summary": "s", "evidence_refs": []},
                "narrative_coherence": {"status": "regressed", "summary": "r", "evidence_refs": ["e"]},
                "image_content_quality": {"status": "insufficient_evidence", "summary": "", "evidence_refs": []},
            },
            "hard_vetoes": [],
            "evidence_of_improvement": [],
        })
        self.assertIn("story_element_coverage", v["dimensions"])
        self.assertEqual(v["dimensions"]["narrative_coherence"]["status"], "regressed")
        # Fixture path still ok; degraded path must set rule_fallback_success false
        from story_video_agent.api_provider import ApiProvider
        api = ApiProvider(force_mock=True, max_calls=0)
        # Without fixture, mock content is error → ok False
        out = call_llm_verifier(api, {"x": 1}, fixture=None, max_retries=0)
        self.assertFalse(out.get("ok"))
        self.assertFalse(out.get("rule_fallback_success", False))


if __name__ == "__main__":
    unittest.main()
