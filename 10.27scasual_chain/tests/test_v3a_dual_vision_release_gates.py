"""P0 regressions: dual-video vision Verifier + release conjunction + timeline mapping."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_video_agent_v3.dual_video_vision_verifier import (
    text_only_verifier_forbidden_result,
    validate_visual_verifier_payload,
)
from story_video_agent_v3.global_story_critic import structural_diagnosis
from story_video_agent_v3.story_timeline import build_story_timeline, placeholder_duration_sec
from story_video_agent_v3.story_video_verifier import (
    compute_release_authorization,
    empty_status_gates,
    timeline_mp4_aligned,
    verify_story_revision,
)


def _edl_pair():
    base = [
        {"segment_id": "seg_title_open", "role": "story_title", "include_in_cut": True,
         "media_in": None, "media_out": None, "placeholder_sec": 3.0, "is_replay": False},
        {"segment_id": "seg_open", "role": "opponent_opening_goal_action", "include_in_cut": True,
         "media_in": 100.0, "media_out": 120.0, "is_replay": False},
        {"segment_id": "seg_build", "role": "buildup_action", "include_in_cut": True,
         "media_in": 200.0, "media_out": 212.0, "is_replay": False},
        {"segment_id": "seg_eq", "role": "equalizer_goal_action", "include_in_cut": True,
         "media_in": 300.0, "media_out": 320.0, "is_replay": False},
        {"segment_id": "seg_ga", "role": "go_ahead_goal_action", "include_in_cut": True,
         "media_in": 400.0, "media_out": 420.0, "is_replay": False},
        {"segment_id": "seg_close", "role": "story_wrap_title", "include_in_cut": True,
         "media_in": None, "media_out": None, "placeholder_sec": 3.0, "is_replay": False},
    ]
    cand = [dict(r) for r in base]
    # Drop non-goal buildup → real EDL change
    for r in cand:
        if r["segment_id"] == "seg_build":
            r["include_in_cut"] = False
    return base, cand


class TimelinePlaceholderTests(unittest.TestCase):
    def test_placeholders_count_toward_story_duration(self):
        base, _ = _edl_pair()
        tl = build_story_timeline(base)
        # media 20+12+20+20=72 + placeholders 3+3=6 → 78
        self.assertAlmostEqual(tl["media_duration_sec"], 72.0, places=2)
        self.assertAlmostEqual(tl["placeholder_duration_sec"], 6.0, places=2)
        self.assertAlmostEqual(tl["story_duration_sec"], 78.0, places=2)
        self.assertEqual(tl["placeholder_segment_count"], 2)

    def test_b_style_delta_explained_by_placeholders(self):
        # Reproduce B: media 107.5 + 3*3.0 placeholders = 116.5
        edl = [
            {"segment_id": "t1", "role": "story_title", "include_in_cut": True,
             "media_in": None, "media_out": None, "placeholder_sec": 3.0},
            {"segment_id": "t2", "role": "arc_background_title", "include_in_cut": True,
             "media_in": None, "media_out": None, "placeholder_sec": 3.0},
            {"segment_id": "m1", "role": "opponent_opening_goal_action", "include_in_cut": True,
             "media_in": 0.0, "media_out": 107.5, "is_replay": False},
            {"segment_id": "t3", "role": "story_wrap_title", "include_in_cut": True,
             "media_in": None, "media_out": None, "placeholder_sec": 3.0},
        ]
        tl = build_story_timeline(edl)
        self.assertAlmostEqual(tl["story_duration_sec"], 116.5, places=2)
        # Critic should not raise large mismatch vs ~116.96 when timeline includes cards.
        diag = structural_diagnosis(edl=edl)
        mismatch = [i for i in diag["issues"] if i["issue_id"] == "story_mp4_timeline_mismatch"]
        self.assertEqual(mismatch, [])  # no mp4 provided → different issue maybe missing mp4


class VisualVerifierCitationTests(unittest.TestCase):
    def test_text_only_forbidden(self):
        out = text_only_verifier_forbidden_result()
        self.assertFalse(out["ok_for_semantic_accept"])
        self.assertEqual(out["semantic_verification_status"], "NOT_EVALUATED")

    def test_improved_without_sent_frame_ids_rejected(self):
        gate = validate_visual_verifier_payload(
            {
                "quality_delta_vs_baseline": "improved",
                "evidence_of_improvement": [
                    {"claim": "better", "evidence_refs": [{"frame_id": "ghost_frame"}]}
                ],
                "accept_candidate": True,
                "hard_vetoes": [],
                "dimensions": {},
            },
            sent_frame_ids=["baseline_opening_0", "candidate_opening_0"],
        )
        self.assertFalse(gate["ok_for_semantic_accept"])
        self.assertEqual(gate["semantic_verification_status"], "NOT_EVALUATED")
        self.assertIn("improved_evidence_refs_not_in_sent_frames", " ".join(gate["reasons"]))

    def test_improved_with_valid_dual_citations_can_pass(self):
        gate = validate_visual_verifier_payload(
            {
                "quality_delta_vs_baseline": "improved",
                "evidence_of_improvement": [{
                    "claim": "cleaner mid",
                    "evidence_refs": [
                        {"frame_id": "baseline_development_1"},
                        {"frame_id": "candidate_development_1"},
                    ],
                }],
                "accept_candidate": True,
                "hard_vetoes": [],
                "dimensions": {
                    "narrative_coherence": {
                        "status": "improved",
                        "summary": "ok",
                        "evidence_refs": [{"frame_id": "candidate_development_1"}],
                    }
                },
            },
            sent_frame_ids=[
                "baseline_opening_0", "candidate_opening_0",
                "baseline_development_1", "candidate_development_1",
            ],
        )
        self.assertTrue(gate["ok_for_semantic_accept"])
        self.assertEqual(gate["semantic_verification_status"], "PASSED")


class VerifyStoryRevisionGatesTests(unittest.TestCase):
    def test_text_fixture_improved_refused(self):
        base, cand = _edl_pair()
        with tempfile.TemporaryDirectory() as td:
            # missing mp4s → hard veto anyway; still check semantic not passed via text
            report = verify_story_revision(
                story={},
                plan={},
                baseline_edl=base,
                candidate_edl=cand,
                baseline_mp4=Path(td) / "missing_b.mp4",
                candidate_mp4=Path(td) / "missing_c.mp4",
                decision="REVISE",
                fixture={
                    "quality_delta_vs_baseline": "improved",
                    "evidence_of_improvement": [{"claim": "text only", "evidence_refs": []}],
                    "accept_candidate": True,
                    "hard_vetoes": [],
                    "dimensions": {},
                },
                sent_frame_ids=[],
                vision_backed=False,
            )
            self.assertFalse(report["candidate_accepted"])
            self.assertEqual(
                report["dual_verifier"]["semantic_verification_status"], "NOT_EVALUATED"
            )

    def test_unknown_frame_citation_refused(self):
        base, cand = _edl_pair()
        with tempfile.TemporaryDirectory() as td:
            b = Path(td) / "b.mp4"
            c = Path(td) / "c.mp4"
            b.write_bytes(b"\x00")
            c.write_bytes(b"\x00")
            # ffprobe may fail → duration None; still exercise citation gate
            report = verify_story_revision(
                story={},
                plan={},
                baseline_edl=base,
                candidate_edl=cand,
                baseline_mp4=b,
                candidate_mp4=c,
                decision="REVISE",
                fixture={
                    "quality_delta_vs_baseline": "improved",
                    "evidence_of_improvement": [{
                        "claim": "x",
                        "evidence_refs": [{"frame_id": "not_sent_frame"}],
                    }],
                    "accept_candidate": True,
                    "hard_vetoes": [],
                    "dimensions": {},
                },
                sent_frame_ids=["baseline_opening_0", "candidate_opening_0"],
                vision_backed=True,
            )
            self.assertFalse(report["candidate_accepted"])

    def test_edl_unchanged_revise_rejected(self):
        base, _ = _edl_pair()
        with tempfile.TemporaryDirectory() as td:
            report = verify_story_revision(
                story={},
                plan={},
                baseline_edl=base,
                candidate_edl=base,
                baseline_mp4=Path(td) / "x.mp4",
                candidate_mp4=Path(td) / "y.mp4",
                decision="REVISE",
                fixture={
                    "quality_delta_vs_baseline": "improved",
                    "evidence_of_improvement": [{
                        "claim": "x",
                        "evidence_refs": [
                            {"frame_id": "baseline_opening_0"},
                            {"frame_id": "candidate_opening_0"},
                        ],
                    }],
                    "accept_candidate": True,
                    "hard_vetoes": [],
                    "dimensions": {},
                },
                sent_frame_ids=["baseline_opening_0", "candidate_opening_0"],
                vision_backed=True,
            )
            self.assertFalse(report["candidate_accepted"])
            self.assertTrue(any(v.get("kind") == "revise_without_edl_change" for v in report["hard_vetoes"]))

    def test_goal_window_change_hard_veto(self):
        base, cand = _edl_pair()
        for r in cand:
            if r["segment_id"] == "seg_eq":
                r["media_out"] = 330.0
        with tempfile.TemporaryDirectory() as td:
            report = verify_story_revision(
                story={}, plan={}, baseline_edl=base, candidate_edl=cand,
                baseline_mp4=Path(td) / "a.mp4", candidate_mp4=Path(td) / "b.mp4",
                decision="REVISE",
            )
            self.assertFalse(report["candidate_accepted"])
            self.assertTrue(
                any(v.get("kind") == "goal_anchor_window_changed" for v in report["hard_vetoes"])
            )


class ReleaseConjunctionTests(unittest.TestCase):
    def test_semantic_alone_insufficient(self):
        gates = empty_status_gates()
        gates.update({
            "workflow_completed": True,
            "final_mp4_exists": True,
            "semantic_verification_passed": True,
            "candidate_rendered": False,
        })
        with tempfile.TemporaryDirectory() as td:
            mp4 = Path(td) / "f.mp4"
            mp4.write_bytes(b"\x00")
            base, cand = _edl_pair()
            rel = compute_release_authorization(
                gates=gates,
                decision="REVISE",
                edl_changed=True,
                candidate_accepted=True,
                goal_anchors_intact=True,
                hard_vetoes=[],
                final_mp4=mp4,
                final_edl=cand,
                diagnosis_issues=[],
                timeline_aligned=True,
            )
            self.assertFalse(rel["release_authorized"])
            self.assertIn("candidate_not_rendered", rel["reasons"])

    def test_unresolved_blocks_release(self):
        gates = empty_status_gates()
        gates.update({
            "candidate_rendered": True,
            "semantic_verification_passed": True,
            "final_mp4_exists": True,
        })
        with tempfile.TemporaryDirectory() as td:
            mp4 = Path(td) / "f.mp4"
            mp4.write_bytes(b"\x00")
            _, cand = _edl_pair()
            rel = compute_release_authorization(
                gates=gates,
                decision="UNRESOLVED",
                edl_changed=True,
                candidate_accepted=True,
                goal_anchors_intact=True,
                hard_vetoes=[],
                final_mp4=mp4,
                final_edl=cand,
                unresolved_critical=True,
            )
            self.assertFalse(rel["release_authorized"])


class MatchAgnosticGuardTests(unittest.TestCase):
    def test_no_match_names_in_verifier_modules(self):
        root = Path(__file__).resolve().parents[1] / "algo" / "story_video_agent_v3"
        for name in (
            "dual_video_vision_verifier.py",
            "story_video_verifier.py",
            "story_timeline.py",
        ):
            text = (root / name).read_text(encoding="utf-8")
            for banned in ("阿联酋", "阿曼", "奥萨苏纳", "克罗地亚", "塞尔塔"):
                self.assertNotIn(banned, text)


@unittest.skipUnless(
    Path("/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_B_osasuna_celta/04_phase5/story_clean.mp4").is_file(),
    "B phase5 unavailable",
)
class BTimelineRootCauseIntegration(unittest.TestCase):
    def test_b_mp4_matches_timeline_with_placeholders(self):
        phase5 = Path(
            "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_B_osasuna_celta/04_phase5"
        )
        edl = json.loads((phase5 / "candidate_edl.json").read_text(encoding="utf-8"))
        if isinstance(edl, dict):
            edl = edl.get("segments") or edl.get("edl") or []
        align = timeline_mp4_aligned(
            edl=edl, mp4=phase5 / "story_clean.mp4", tolerance_sec=2.0
        )
        self.assertTrue(align["aligned"], align)
        self.assertGreater(float(align["placeholder_duration_sec"]), 8.0)
        self.assertAlmostEqual(
            float(align["story_duration_sec"]),
            float(align["media_duration_sec"]) + float(align["placeholder_duration_sec"]),
            places=2,
        )
        # Root cause: placeholders, not an 8s threshold hack
        self.assertEqual(
            align["root_cause_hint"], "placeholder_title_cards_included_in_story_duration"
        )


if __name__ == "__main__":
    unittest.main()
