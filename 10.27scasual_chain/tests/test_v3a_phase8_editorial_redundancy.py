"""No-HTTP testing of a genuine non-additive story candidate from cited frames.

Synthetic JPEG bytes validate provenance/control-flow, not actual model
accuracy or story comprehension.
"""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.story_editorial_redundancy import (
    validate_editorial_redundancy_claims,
)
from story_video_agent_v3.story_fullcut_learning import (
    enforce_confirmed_nonadditive_edits,
)
from story_video_agent_v3.story_revision_planner import plan_from_diagnosis
from story_video_agent_v3.self_revise_agent import apply_candidate_revision
from story_video_agent_v3.story_timeline import build_story_timeline


def _edl():
    return [
        {"segment_id": "setup", "role": "deficit_setup",
         "media_in": 10.0, "media_out": 18.0, "include_in_cut": True},
        {"segment_id": "repeat", "role": "buildup_action",
         "media_in": 30.0, "media_out": 37.0, "include_in_cut": True},
        {"segment_id": "goal", "role": "equalizer_goal_action",
         "media_in": 60.0, "media_out": 68.0, "include_in_cut": True},
    ]


def _make_review(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    frames = []
    for fid, seg in (("frame_setup", "setup"), ("frame_repeat", "repeat")):
        path = root / (fid + ".jpg")
        path.write_bytes(("synthetic " + fid).encode("utf-8"))
        frames.append({"frame_id": fid, "segment_id": seg, "path": str(path)})
    claims = [{
        "target_segment_id": "repeat",
        "comparison_segment_id": "setup",
        "observed_fact": "Both clips independently repeat the same pressure description",
        "why_redundant": "The second clip provides no distinct story state and delays the payoff",
        "evidence_refs": [
            {"frame_id": "frame_setup", "note": "early pressure setup"},
            {"frame_id": "frame_repeat", "note": "repeated visual setup"},
        ],
    }]
    return frames, claims


def _validate(frames, claims, edl=None):
    return validate_editorial_redundancy_claims(
        claims, frame_bindings=frames,
        timeline=build_story_timeline(edl or _edl()),
        protected_goal_ids=["goal"],
    )


class TestEditorialRedundancy(unittest.TestCase):
    def test_cited_non_goal_redundancy_becomes_executable_drop_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            frames, claims = _make_review(Path(td))
            out = _validate(frames, claims)
            self.assertEqual(len(out["issues"]), 1)
            issue = out["issues"][0]
            self.assertEqual(issue["preferred_drop_segment_id"], "repeat")
            self.assertEqual(issue["evidence_tier"], "DEFECT_CONFIRMED")
            self.assertTrue(out["does_not_authorize_best_promotion"])
            # Unchanged EDL part can be removed without any invented source PTS.
            diagnosis = {
                "issues": [issue], "protected_goal_segment_ids": ["goal"],
            }
            plan = plan_from_diagnosis(
                diagnosis, use_fullcut_learning=True,
                require_narrative_fit=True,
            )
            self.assertEqual(plan["decision"], "REVISE")
            self.assertEqual(plan["revision_intents"][0]["action"], "drop")
            verified = enforce_confirmed_nonadditive_edits(
                plan, diagnosis=diagnosis, edl=_edl(),
            )
            self.assertEqual(
                verified["revision_intents"][0]["target_segment_id"], "repeat"
            )
            self.assertEqual(verified["nonadditive_apply_gate"]["n_blocked"], 0)
            unchanged = _edl()
            modified, applied = apply_candidate_revision(
                unchanged, verified["revision_intents"], observations=[],
            )
            self.assertTrue(unchanged[1]["include_in_cut"])
            self.assertFalse(modified[1]["include_in_cut"])
            self.assertTrue(modified[2]["include_in_cut"])
            self.assertTrue(any(
                a.get("action") == "drop" and a.get("status") == "applied"
                for a in applied.get("applied") or []
            ))

    def test_citing_only_one_segment_does_not_confirm_redundancy(self):
        with tempfile.TemporaryDirectory() as td:
            frames, claims = _make_review(Path(td))
            claims[0]["evidence_refs"] = [
                {"frame_id": "frame_repeat", "note": "one clip only"},
            ]
            out = _validate(frames, claims)
            self.assertFalse(out["issues"])
            self.assertEqual(
                out["rejected"][0]["reason"], "missing_or_fabricated_cited_frame",
            )

    def test_hallucinated_frame_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            frames, claims = _make_review(Path(td))
            claims[0]["evidence_refs"].append(
                {"frame_id": "not_sent", "note": "fabricated"}
            )
            out = _validate(frames, claims)
            self.assertFalse(out["issues"])

    def test_goal_or_scoreboard_cannot_be_editorial_drop_target(self):
        with tempfile.TemporaryDirectory() as td:
            frames, claims = _make_review(Path(td))
            frame_goal = Path(td) / "goal.jpg"
            frame_goal.write_bytes(b"synthetic goal frame")
            frames[1] = {
                "frame_id": "frame_repeat",
                "segment_id": "goal",
                "path": str(frame_goal),
            }
            claims[0]["target_segment_id"] = "goal"
            out = _validate(frames, claims)
            self.assertFalse(out["issues"])
            self.assertEqual(
                out["rejected"][0]["reason"], "protected_or_essential_story_segment",
            )

    def test_missing_actual_frame_bytes_cannot_confirm_target(self):
        with tempfile.TemporaryDirectory() as td:
            frames, claims = _make_review(Path(td))
            Path(frames[1]["path"]).unlink()
            out = _validate(frames, claims)
            self.assertEqual(out["issues"], [])

    def test_model_cannot_delete_arbitrary_non_goal_segment(self):
        with tempfile.TemporaryDirectory() as td:
            frames, claims = _make_review(Path(td))
            issue = _validate(frames, claims)["issues"][0]
            diag = {"issues": [issue], "protected_goal_segment_ids": ["goal"]}
            forged = {"decision": "REVISE", "revision_intents": [{
                "action": "drop",
                "intent_id": "model_target_swap",
                "issue_id": issue["issue_id"],
                "target_segment_id": "setup",
            }]}
            validated = enforce_confirmed_nonadditive_edits(
                forged, diagnosis=diag, edl=_edl(),
            )
            self.assertEqual(validated["decision"], "UNRESOLVED")
            self.assertEqual(
                validated["revision_intents"][0]["action"], "mark_unresolved"
            )

    def test_protected_goal_cannot_be_deleted_by_claimed_confirmation(self):
        diag = {
            "protected_goal_segment_ids": ["goal"],
            "issues": [{
                "issue_id": "model_claimed_redundancy",
                "category": "redundancy",
                "story_defect_confirmed": True,
                "preferred_drop_segment_id": "goal",
                "segment_ids": ["goal", "setup"],
            }],
        }
        plan = {"decision": "REVISE", "revision_intents": [{
            "action": "drop", "issue_id": "model_claimed_redundancy",
            "target_segment_id": "goal",
        }]}
        validated = enforce_confirmed_nonadditive_edits(
            plan, diagnosis=diag, edl=_edl(),
        )
        self.assertEqual(validated["decision"], "UNRESOLVED")
        self.assertTrue(validated["nonadditive_apply_gate"]["blocked_intents"])


if __name__ == "__main__":
    unittest.main()
