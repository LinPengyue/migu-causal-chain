"""P10-C: zero-cost proof of isolated exploratory edit safety and blind output.

No result here is an actual video/story quality judgment.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.story_exploratory_cut import (
    execute_exploratory_trial,
    propose_exploratory_cut,
)
from story_video_agent_v3.story_paid_eval import run_llm_revision_planner
from story_video_agent_v3.story_e2e_cli import build_parser
from story_video_agent_v3.story_e2e_agent import StoryE2EInputs
from story_video_agent_v3.story_timeline import build_story_timeline


def _edl():
    return [
        {"segment_id": "title", "role": "title_open", "include_in_cut": True,
         "placeholder_sec": 2.5},
        {"segment_id": "intro", "role": "opponent_opening", "media_in": 10.0,
         "media_out": 18.0, "include_in_cut": True},
        {"segment_id": "buildup_a", "role": "buildup_action", "media_in": 20.0,
         "media_out": 30.0, "include_in_cut": True},
        {"segment_id": "buildup_b", "role": "buildup_pressure", "media_in": 33.0,
         "media_out": 43.0, "include_in_cut": True},
        {"segment_id": "goal", "role": "equalizer_goal_action", "media_in": 60.0,
         "media_out": 69.0, "include_in_cut": True},
        {"segment_id": "end", "role": "ending_wrap", "media_in": 80.0,
         "media_out": 85.0, "include_in_cut": True},
    ]


def _proposal(action="drop", target="buildup_b", **kwargs):
    return {
        "action": action,
        "target_segment_id": target,
        "hypothesis": "The second pressure beat may repeat already established tension",
        "expected_effect": "A leaner rising action might improve pacing",
        "risk": "It might remove useful team movement context",
        **kwargs,
    }


def _fake_renderer(*, plan, video, edl, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "story_clean.mp4"
    target.write_bytes(b"FAKE candidate story fullcut for module test")
    return {"ok": True, "story_clean": str(target)}


class TestPhase10CExploration(unittest.TestCase):
    def test_drop_unprotected_segment_keeps_parent_and_all_goal_anchors(self):
        parent = _edl()
        snapshot = copy.deepcopy(parent)
        result = propose_exploratory_cut(
            baseline_edl=parent, proposal=_proposal(), source="FIXTURE",
        )
        self.assertEqual(result["status"], "PROPOSED_SAFETY_SCREENED")
        cand = result["candidate_edl"]
        self.assertEqual(parent, snapshot)
        self.assertFalse(next(x for x in cand if x["segment_id"] == "buildup_b")["include_in_cut"])
        self.assertTrue(next(x for x in cand if x["segment_id"] == "goal")["include_in_cut"])
        self.assertTrue(result["protected_anchors_preserved"])
        self.assertFalse(result["human_quality_improved"])
        self.assertFalse(result["promote_best"])

    def test_safe_trim_is_subwindow_and_never_adds_new_source_footage(self):
        result = propose_exploratory_cut(
            baseline_edl=_edl(),
            proposal=_proposal("trim", "buildup_a", media_in=22.0, media_out=29.0),
            source="FIXTURE",
        )
        self.assertEqual(result["status"], "PROPOSED_SAFETY_SCREENED")
        trim = next(x for x in result["candidate_edl"] if x["segment_id"] == "buildup_a")
        self.assertEqual([trim["media_in"], trim["media_out"]], [22.0, 29.0])
        self.assertFalse(result["new_source_windows"])

    def test_no_outside_source_time_or_aggressive_trim(self):
        for bounds in ((17.0, 29.0), (22.0, 32.0), (22.0, 23.0), (20.0, 30.0)):
            result = propose_exploratory_cut(
                baseline_edl=_edl(),
                proposal=_proposal("trim", "buildup_a",
                                   media_in=bounds[0], media_out=bounds[1]),
                source="FIXTURE",
            )
            self.assertEqual(result["status"], "BLOCKED", bounds)
            self.assertIsNone(result["candidate_edl"])

    def test_no_goal_scoreboard_title_opening_ending_or_protected_override(self):
        base = _edl()
        base.insert(5, {"segment_id": "score", "role": "equalizer_scoreboard",
                        "media_in": 71.0, "media_out": 75.0})
        for target in ("goal", "score", "title", "intro", "end"):
            result = propose_exploratory_cut(
                baseline_edl=base, proposal=_proposal(target=target), source="FIXTURE",
            )
            self.assertEqual(result["reason"], "protected_story_anchor", target)

    def test_replay_or_slow_motion_blocks_exploratory_render(self):
        for variant in ({"is_replay": True}, {"shot_kind": "slow_motion_view"}):
            base = _edl()
            base[2].update(variant)
            r = propose_exploratory_cut(
                baseline_edl=base, proposal=_proposal(), source="FIXTURE",
            )
            self.assertEqual(r["status"], "BLOCKED")

    def test_reorder_that_breaks_match_pts_is_blocked(self):
        result = propose_exploratory_cut(
            baseline_edl=_edl(),
            proposal=_proposal("reorder", "buildup_b",
                               insert_before_segment_id="buildup_a"),
            source="FIXTURE",
        )
        self.assertEqual(result["reason"], "candidate_source_pts_not_monotonic")

    def test_insert_replace_never_bypass_live_evidence_requirement(self):
        for action in ("search_add", "insert", "replace"):
            result = propose_exploratory_cut(
                baseline_edl=_edl(),
                proposal=_proposal(action),
                source="REAL_LLM",
            )
            self.assertEqual(result["status"], "BLOCKED")

    def test_no_edl_rewrite_on_invalid_model_target(self):
        for wrong in ("not_a_real_segment", "", None):
            result = propose_exploratory_cut(
                baseline_edl=_edl(),
                proposal=_proposal(target=wrong), source="REAL_LLM",
            )
            self.assertEqual(result["status"], "BLOCKED")

    def test_model_cannot_mark_unverified_content_as_real_provider(self):
        result = propose_exploratory_cut(
            baseline_edl=_edl(),
            proposal=_proposal(), source="MODEL_CLAIMED_REAL",
        )
        self.assertEqual(result["reason"], "unsupported_proposal_provenance")

    def test_missing_risk_or_empty_hypothesis_denied(self):
        for change in ({"risk": ""}, {"hypothesis": "too short"}, {"expected_effect": ""}):
            result = propose_exploratory_cut(
                baseline_edl=_edl(),
                proposal=_proposal(**change), source="FIXTURE",
            )
            self.assertEqual(result["status"], "BLOCKED")

    def test_isolated_blind_pair_is_full_mp4_and_separate_key(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            base_mp4, src_mp4 = root / "baseline.mp4", root / "original_match.mp4"
            base_mp4.write_bytes(b"FAKE baseline fullcut for module test")
            src_mp4.write_bytes(b"FAKE raw match mp4 for module test")
            edl = _edl()
            original = copy.deepcopy(edl)
            trial = execute_exploratory_trial(
                baseline_edl=edl, proposal=_proposal(), source="FIXTURE",
                baseline_mp4=base_mp4, source_mp4=src_mp4,
                story_plan={"title": "long story"},
                out_dir=root / "trial",
                renderer=_fake_renderer,
                integrity_checker=lambda **kwargs: {
                    "aligned": True, "method": "SYNTHETIC_TEST_STUB",
                },
            )
            self.assertEqual(trial["status"], "EXPLORATORY_RENDERED_NOT_VERIFIED")
            self.assertEqual(trial["blind_pair_status"], "BLIND_PAIR_READY")
            self.assertFalse(trial["release_authorized"])
            self.assertFalse(trial["promote_best"])
            self.assertEqual(edl, original)
            blind = root / "trial" / "blind_review"
            self.assertEqual(
                sorted(p.name for p in blind.iterdir()),
                ["X.mp4", "Y.mp4", "review_instructions.json"],
            )
            contents = {(blind / side).read_bytes() for side in ("X.mp4", "Y.mp4")}
            self.assertEqual(contents, {
                b"FAKE baseline fullcut for module test",
                b"FAKE candidate story fullcut for module test",
            })
            key = json.loads((root / "trial" / "PRIVATE_unblinding.json").read_text())
            self.assertEqual({key["X"], key["Y"]}, {"baseline", "candidate"})
            self.assertNotIn("PRIVATE_unblinding.json", [p.name for p in blind.iterdir()])

    def test_misaligned_fullcut_never_exposes_blind_pair(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            base, source = root / "baseline.mp4", root / "source.mp4"
            base.write_bytes(b"fixture baseline")
            source.write_bytes(b"fixture source")
            def checker(*, edl, mp4):
                return {"aligned": mp4.name == "baseline.mp4",
                        "method": "SYNTHETIC_TEST_STUB"}
            result = execute_exploratory_trial(
                baseline_edl=_edl(), proposal=_proposal(), source="FIXTURE",
                baseline_mp4=base, source_mp4=source,
                story_plan={}, out_dir=root / "trial", renderer=_fake_renderer,
                integrity_checker=checker,
            )
            self.assertEqual(result["status"], "RENDER_FAILED")
            self.assertEqual(result["reason"], "baseline_or_candidate_fullcut_timeline_misaligned")
            self.assertEqual(result["blind_pair_status"], "NO_CANDIDATE_PAIR")
            self.assertFalse((root / "trial" / "blind_review").exists())

    def test_failed_renderer_must_not_produce_blind_pair(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            base, source = root / "baseline.mp4", root / "source.mp4"
            base.write_bytes(b"baseline")
            source.write_bytes(b"source")

            def failed(**kwargs):
                return {"ok": False, "story_clean": None}

            result = execute_exploratory_trial(
                baseline_edl=_edl(), proposal=_proposal(), source="FIXTURE",
                baseline_mp4=base, source_mp4=source,
                story_plan={}, out_dir=root / "trial", renderer=failed,
            )
            self.assertEqual(result["status"], "RENDER_FAILED")
            self.assertEqual(result["blind_pair_status"], "NO_CANDIDATE_PAIR")
            self.assertFalse((root / "trial" / "blind_review").exists())

    def test_no_mp4_refuses_to_fabricate_story_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            result = execute_exploratory_trial(
                baseline_edl=_edl(), proposal=_proposal(), source="FIXTURE",
                baseline_mp4=root / "missing.mp4", source_mp4=root / "source.mp4",
                story_plan={}, out_dir=root / "trial", renderer=_fake_renderer,
            )
            self.assertFalse(result["candidate_rendered"])
            self.assertEqual(result["status"], "BLOCKED")

    def test_cli_optin_is_off_by_default(self):
        parsed = build_parser().parse_args([
            "--match-json", "match.json", "--source-mp4", "raw.mp4",
            "--out-dir", "out",
        ])
        self.assertFalse(parsed.phase10_explore)
        self.assertIsNone(parsed.phase10_explore_fixture)
        inp = StoryE2EInputs(
            match_json=Path("match.json"), source_mp4=Path("raw.mp4"),
            out_dir=Path("out"),
        )
        self.assertFalse(inp.phase10_explore)

    def test_target_is_bounded_existing_source_not_just_duration_padding(self):
        baseline = _edl()
        out = propose_exploratory_cut(
            baseline_edl=baseline, proposal=_proposal("trim", "buildup_b",
                                                      media_in=34.0, media_out=41.0),
            source="REAL_LLM",
        )
        self.assertEqual(out["status"], "PROPOSED_SAFETY_SCREENED")
        a = build_story_timeline(baseline)
        b = build_story_timeline(out["candidate_edl"])
        self.assertLess(b["story_duration_sec"], a["story_duration_sec"])
        self.assertEqual(
            [s["media_in"] for s in b["segments"] if "goal_action" in s["role"]],
            [60.0],
        )


class _MockPlanner:
    def __init__(self):
        self.calls = 0
        self.prompt = ""

    def revise_decision(self, *, system_prompt, user_prompt, mock_decision):
        self.calls += 1
        self.prompt = user_prompt
        return {
            "provider_mode": "openai_compatible",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            "content": json.dumps({
                "decision": "UNRESOLVED",
                "revision_intents": [],
                "exploratory_intents": [_proposal()],
                "rationale": "No confirmed defect; optional candidate only",
            }),
        }


class TestPhase10CPlannerOptional(unittest.TestCase):
    def test_one_call_returns_separate_hypothesis_without_formal_revise(self):
        model = _MockPlanner()
        with tempfile.TemporaryDirectory() as d:
            result = run_llm_revision_planner(
                model, diagnosis={"issues": [], "timeline": build_story_timeline(_edl())},
                vlm_critic={}, protected_goal_ids=["goal"], audit_dir=Path(d),
                allow_exploratory_proposals=True,
            )
        self.assertEqual(model.calls, 1)
        self.assertIn("PHASE10-C OPTIONAL EXPLORATION", model.prompt)
        self.assertEqual(result["decision"], "UNRESOLVED")
        self.assertEqual(result["revision_intents"], [])
        self.assertEqual(len(result["exploratory_intents"]), 1)

    def test_default_model_proposal_is_not_enabled(self):
        model = _MockPlanner()
        with tempfile.TemporaryDirectory() as d:
            result = run_llm_revision_planner(
                model, diagnosis={"issues": [], "timeline": build_story_timeline(_edl())},
                vlm_critic={}, protected_goal_ids=["goal"], audit_dir=Path(d),
            )
        self.assertNotIn("PHASE10-C OPTIONAL EXPLORATION", model.prompt)
        self.assertEqual(result["exploratory_intents"], [])


if __name__ == "__main__":
    unittest.main()
