"""Zero-cost Oman (A) tests: Composer → V3-A evidence handoff + Planner dispositions."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from story_video_agent_v3.composer_evidence_handoff import (
    DISPOSITION_INSPECT,
    DISPOSITION_KEEP,
    VISUAL_HISTORICAL_OBS_ONLY,
    VISUAL_NOT_OBSERVED,
    build_composer_evidence_handoff,
    map_disposition_to_action,
    project_segment_handoff,
)
from story_video_agent_v3.self_revise_agent import (
    apply_candidate_revision,
    build_trusted_anchors,
    compact_context,
    validate_planner_output,
)

FRESH_RUN = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/"
    "fresh_e2e_A_real_20261105_183136"
)
BASELINE_EDL = FRESH_RUN / "05_v3a/_baseline_phase5/candidate_edl.json"
BASELINE_PLAN = FRESH_RUN / "05_v3a/_baseline_phase5/story_plan.json"
BASELINE_STORY = FRESH_RUN / "05_v3a/_baseline_phase5/t01_story.json"
VLM_OBS = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/A_vlm_smoke_20261105_210200/observation.json"
)
OPENING = "seg_opponent_opening_goal_action"


def _load(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@unittest.skipUnless(BASELINE_EDL.is_file(), "Oman fresh E2E baseline EDL missing")
class ComposerHandoffOmanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edl = _load(BASELINE_EDL)
        cls.plan = _load(BASELINE_PLAN) if BASELINE_PLAN.is_file() else {
            "match_id": "uae_oman",
            "story_scope": {"selected_arc": {
                "behind_start": {"t_sec": 1410.43, "score": "0:1"},
                "equalizer": {"t_sec": 6536.0, "score": "1:1"},
                "go_ahead": {"t_sec": 6958.0, "score": "2:1"},
            }},
        }
        cls.story = _load(BASELINE_STORY) if BASELINE_STORY.is_file() else {
            "match_id": cls.plan.get("match_id"), "title": "A", "protagonist": "left",
        }
        cls.opening = next(
            r for r in cls.edl
            if r.get("segment_id") == OPENING
            or r.get("role") == "opponent_opening_goal_action"
        )

    def test_handoff_passes_composer_fields_to_planner_context(self):
        audit = {
            "hard_gate_findings": [],
            "diagnostic_issues": [],
            "revision_requests": [],
            "unverified": ["live_vs_replay_visual_truth"],
            "structural_proxy_pass": True,
        }
        ctx = compact_context(
            story=self.story, plan=self.plan, edl=self.edl, audit=audit,
            video_duration=9000.0,
        )
        self.assertIn("composer_evidence_handoff", ctx)
        handoff = ctx["composer_evidence_handoff"]
        self.assertEqual(handoff["schema"], "composer_evidence_handoff_v1")
        self.assertFalse(handoff["composer_reexecuted"])
        seg = handoff["segments"][OPENING]
        for key in (
            "segment_id", "role", "media_in", "media_out", "event_ids", "frame_ids",
            "time_provenance", "evidence_refs", "selection_reason",
            "render_eligibility", "blocking_reasons", "is_replay",
            "is_replay_basis", "visual_verification_status",
        ):
            self.assertIn(key, seg)
        self.assertEqual(seg["media_in"], self.opening["media_in"])
        self.assertEqual(seg["media_out"], self.opening["media_out"])
        self.assertEqual(seg["event_ids"], self.opening["event_ids"])
        self.assertEqual(seg["selection_reason"], self.opening["selection_reason"])
        self.assertEqual(seg["render_eligibility"], "candidate_only")
        self.assertTrue(seg["evidence_refs"])
        self.assertEqual(seg["evidence_refs"][0].get("evidence_grade"), "rule_or_event_association")
        self.assertEqual(seg["visual_verification_status"], VISUAL_NOT_OBSERVED)
        self.assertTrue(seg["is_replay_basis"]["not_visual_first_live"])
        self.assertFalse(seg["evidence_grades"]["first_live_verified"])
        # Brief EDL still present (compat); handoff is additive.
        brief = next(r for r in ctx["candidate_edl"] if r.get("segment_id") == OPENING)
        self.assertNotIn("evidence_refs", brief)
        self.assertIn("evidence_refs", seg)
        self.assertEqual(
            seg["suggested_planner_disposition"]["disposition"], DISPOSITION_INSPECT,
        )

    def test_planner_can_explain_inspect_without_blanket_research(self):
        handoff = build_composer_evidence_handoff(self.edl)
        opening = handoff["segments"][OPENING]
        disp = opening["suggested_planner_disposition"]
        self.assertEqual(disp["disposition"], DISPOSITION_INSPECT)
        self.assertTrue(disp["prefer_tools"])
        self.assertIn("visually_unverified", disp["rationale"])
        # Mapping: INSPECT → keep (+ tools), not search_add for every goal.
        self.assertEqual(map_disposition_to_action("INSPECT"), "keep")
        anchors = build_trusted_anchors(self.plan, self.edl)
        out = validate_planner_output(
            {
                "diagnoses": [{
                    "issue_id": "d_open",
                    "problem": opening["suggested_planner_disposition"]["rationale"],
                    "severity": "P1",
                    "target_segment_id": OPENING,
                    "evidence_refs": ["composer_handoff"],
                }],
                "revision_intents": [{
                    "disposition": "INSPECT",
                    "target_segment_id": OPENING,
                    "role": "opponent_opening_goal_action",
                    "anchor_id": f"edl:{OPENING}",
                    "rationale": disp["rationale"],
                }],
                "video_tool_requests": [{
                    "tool": "vlm_observe",
                    "anchor_id": f"edl:{OPENING}",
                    "question": "Confirm live goal action vs replay in composer window",
                }],
                "notes": "directed_inspect_only",
            },
            trusted_anchors=anchors,
            video_duration=9000.0,
        )
        self.assertEqual(out["revision_intents"][0]["action"], "keep")
        self.assertEqual(out["revision_intents"][0]["disposition"], "INSPECT")
        self.assertEqual(len(out["video_tool_requests"]), 1)
        self.assertEqual(out["video_tool_requests"][0]["anchor_id"], f"edl:{OPENING}")

    def test_keep_without_new_evidence_does_not_mutate_edl(self):
        anchors = build_trusted_anchors(self.plan, self.edl)
        validated = validate_planner_output(
            {
                "diagnoses": [{
                    "issue_id": "d1",
                    "problem": "no new visual evidence",
                    "severity": "P2",
                    "target_segment_id": OPENING,
                }],
                "revision_intents": [{
                    "action": "KEEP",
                    "target_segment_id": OPENING,
                    "rationale": "retain composer candidate",
                }],
                "video_tool_requests": [],
                "notes": "keep",
            },
            trusted_anchors=anchors,
            video_duration=9000.0,
        )
        before = copy.deepcopy(self.edl)
        after, meta = apply_candidate_revision(
            before,
            validated["revision_intents"],
            [],
        )
        # KEEP records intent but must not change media windows / segment set.
        self.assertEqual(
            [(r.get("segment_id"), r.get("media_in"), r.get("media_out"), r.get("include_in_cut"))
             for r in after],
            [(r.get("segment_id"), r.get("media_in"), r.get("media_out"), r.get("include_in_cut"))
             for r in before],
        )
        self.assertTrue(meta.get("applied"))
        self.assertTrue(all(a.get("action") == "keep" for a in meta["applied"]))
        self.assertTrue(all(a.get("status") == "recorded" for a in meta["applied"]))

    @unittest.skipUnless(VLM_OBS.is_file(), "prior Qwen observation artifact missing")
    def test_historical_qwen_obs_reusable_not_first_live(self):
        obs = _load(VLM_OBS)
        handoff = build_composer_evidence_handoff(self.edl, prior_observations=[obs])
        seg = handoff["segments"][OPENING]
        self.assertEqual(seg["visual_verification_status"], VISUAL_HISTORICAL_OBS_ONLY)
        self.assertTrue(seg["historical_observations"])
        self.assertTrue(seg["historical_observations"][0]["cannot_certify_first_live"])
        self.assertTrue(seg["historical_observations"][0]["observation_only"])
        self.assertFalse(seg["evidence_grades"]["first_live_verified"])
        self.assertNotEqual(seg["visual_verification_status"], "FIRST_LIVE_VERIFIED")
        # Smoke obs had observed_shot=false → still INSPECT, not silent KEEP-as-verified.
        self.assertEqual(
            seg["suggested_planner_disposition"]["disposition"], DISPOSITION_INSPECT,
        )

    def test_repair_disposition_alone_rejected(self):
        anchors = build_trusted_anchors(self.plan, self.edl)
        out = validate_planner_output(
            {
                "diagnoses": [{"issue_id": "d", "problem": "x", "severity": "P1"}],
                "revision_intents": [{
                    "disposition": "REPAIR",
                    "target_segment_id": OPENING,
                    "rationale": "needs concrete edit verb",
                }],
                "video_tool_requests": [{
                    "tool": "vlm_observe",
                    "anchor_id": f"edl:{OPENING}",
                }],
            },
            trusted_anchors=anchors,
            video_duration=9000.0,
        )
        self.assertEqual(out["revision_intents"], [])
        self.assertTrue(out["dropped_intents"])
        self.assertEqual(
            out["dropped_intents"][0]["reason"],
            "repair_disposition_needs_concrete_action",
        )

    def test_project_opening_row_unit(self):
        proj = project_segment_handoff(self.opening)
        self.assertEqual(proj["segment_id"], OPENING)
        self.assertIn("time_provenance", proj)
        self.assertEqual(proj["time_provenance"].get("source"), "linked_live_goal_event")


class DispositionMappingCompatTests(unittest.TestCase):
    def test_disposition_aliases(self):
        self.assertEqual(map_disposition_to_action("KEEP"), "keep")
        self.assertEqual(map_disposition_to_action("INSPECT"), "keep")
        self.assertEqual(map_disposition_to_action("UNRESOLVED"), "mark_unresolved")
        self.assertIsNone(map_disposition_to_action("REPAIR"))


if __name__ == "__main__":
    unittest.main()
