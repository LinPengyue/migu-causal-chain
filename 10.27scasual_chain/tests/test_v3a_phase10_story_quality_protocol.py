"""Zero-HTTP checks: no model screen / single rater can authorize BEST."""
import copy
import unittest

from story_video_agent_v3.story_quality_protocol import (
    DIMENSIONS, G0_GATES, RATING_SCHEMA, ALLOCATION_SCHEMA,
    evaluate_blind_story_pair,
)


def _scores(n=4):
    return {name: n for name in DIMENSIONS}


def _bundle(n=3, candidate="Y"):
    reviews = []
    for i in range(n):
        reviews.append({
            "rater_id": "human_%d" % i,
            "preference": candidate + "_STRONG",
            "scores": {
                "X": _scores(3) if candidate == "Y" else _scores(5),
                "Y": _scores(5) if candidate == "Y" else _scores(3),
            },
            "issues": [],
        })
    allocation = {
        "schema": ALLOCATION_SCHEMA, "pair_id": "pair_1",
        "X": "baseline", "Y": "candidate",
    }
    ratings = {"schema": RATING_SCHEMA, "pair_id": "pair_1", "reviews": reviews}
    gates = {"gates": {side: {g: "PASS" for g in G0_GATES} for side in ("X", "Y")}}
    return ratings, allocation, gates


class TestStoryQualityProtocol(unittest.TestCase):
    def test_clear_blind_human_consensus_recommends_not_auto_promotes(self):
        args = _bundle()
        out = evaluate_blind_story_pair(*args)
        self.assertEqual(out["decision"], "IMPROVED_HUMAN_EVIDENCE")
        self.assertTrue(out["recommend_promotion"])
        self.assertFalse(out["automatic_best_update_allowed"])
        self.assertEqual(out["candidate_minus_baseline"], 40.0)

    def test_one_person_only_development_feedback(self):
        out = evaluate_blind_story_pair(*_bundle(n=1))
        self.assertEqual(out["decision"], "DEVELOPMENT_FEEDBACK_ONLY")
        self.assertFalse(out["recommend_promotion"])

    def test_candidate_violation_blocks_even_good_votes(self):
        ratings, alloc, gates = _bundle()
        gates["gates"]["Y"]["first_live"] = "FAIL"
        out = evaluate_blind_story_pair(ratings, alloc, gates)
        self.assertEqual(out["decision"], "REJECTED_G0")

    def test_unknown_gate_blocks_promotion(self):
        ratings, alloc, gates = _bundle()
        gates["gates"]["Y"]["source_traceability"] = "UNKNOWN"
        self.assertEqual(evaluate_blind_story_pair(ratings, alloc, gates)["decision"], "UNVERIFIED_G0")

    def test_critical_issue_blocks_promotion(self):
        ratings, alloc, gates = _bundle()
        ratings["reviews"][0]["issues"] = [{
            "side": "Y", "severity": "critical",
            "description": "Wrong result attributed to the wrong team",
        }]
        self.assertEqual(evaluate_blind_story_pair(ratings, alloc, gates)["decision"], "REJECTED_CRITICAL_ISSUE")

    def test_tie_no_false_improvement(self):
        ratings, alloc, gates = _bundle()
        for review in ratings["reviews"]:
            review["preference"] = "TIE"
        self.assertEqual(evaluate_blind_story_pair(ratings, alloc, gates)["decision"], "NOT_IMPROVED")

    def test_incomplete_story_quality_prevents_promotion(self):
        ratings, alloc, gates = _bundle()
        for review in ratings["reviews"]:
            review["scores"]["Y"]["story_completeness"] = 2
            review["scores"]["Y"]["narrative_coherence"] = 2
        self.assertEqual(evaluate_blind_story_pair(ratings, alloc, gates)["decision"], "NOT_IMPROVED")

    def test_duplicate_raters_rejected(self):
        ratings, alloc, gates = _bundle()
        ratings["reviews"][1]["rater_id"] = "human_0"
        with self.assertRaises(ValueError):
            evaluate_blind_story_pair(ratings, alloc, gates)

    def test_review_packet_cannot_have_unblinding(self):
        ratings, alloc, gates = _bundle()
        ratings["allocation"] = {"Y": "candidate"}
        with self.assertRaises(ValueError):
            evaluate_blind_story_pair(ratings, alloc, gates)

    def test_bad_scores_rejected(self):
        ratings, alloc, gates = _bundle()
        ratings["reviews"][0]["scores"]["Y"]["story_completeness"] = True
        with self.assertRaises(ValueError):
            evaluate_blind_story_pair(ratings, alloc, gates)

    def test_candidate_on_x_unblind_is_not_order_sensitive(self):
        ratings, alloc, gates = _bundle(candidate="X")
        alloc["X"], alloc["Y"] = "candidate", "baseline"
        out = evaluate_blind_story_pair(ratings, alloc, gates)
        self.assertEqual(out["decision"], "IMPROVED_HUMAN_EVIDENCE")
        self.assertEqual(out["candidate_side"], "X")

    def test_minor_score_advantage_is_not_automatic_improvement(self):
        ratings, alloc, gates = _bundle()
        for review in ratings["reviews"]:
            review["scores"]["X"] = {key: 4 for key in DIMENSIONS}
            review["scores"]["Y"] = {key: 4 for key in DIMENSIONS}
        self.assertEqual(
            evaluate_blind_story_pair(ratings, alloc, gates)["decision"],
            "PROMISING_NEEDS_MORE_EVIDENCE",
        )


if __name__ == "__main__":
    unittest.main()
