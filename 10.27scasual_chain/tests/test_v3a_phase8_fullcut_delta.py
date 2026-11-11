"""Zero-HTTP tests for measured full-cut EDL cost and conservative quality state."""
import unittest

from story_video_agent_v3.story_fullcut_delta import compare_fullcut_edls


class TestFullcutDelta(unittest.TestCase):
    def test_insert_measures_cost_but_does_not_claim_improvement(self):
        baseline = [
            {"segment_id": "a", "media_in": 0, "media_out": 10, "role": "setup"},
            {"segment_id": "b", "media_in": 100, "media_out": 110, "role": "result"},
        ]
        candidate = [
            baseline[0],
            {"segment_id": "bridge", "media_in": 40, "media_out": 56, "role": "bridge"},
            baseline[1],
        ]
        result = compare_fullcut_edls(baseline, candidate)
        self.assertEqual(result["baseline_duration_sec"], 20)
        self.assertEqual(result["candidate_duration_sec"], 36)
        self.assertEqual(result["duration_delta_sec"], 16)
        self.assertEqual(result["added_source_segments"][0]["segment_id"], "bridge")
        self.assertEqual(result["candidate_better_than_baseline"], "UNVERIFIED")
        self.assertFalse(result["authorizes_promote_best"])

    def test_no_change_and_untrusted_label_do_not_authorize_promote(self):
        edl = [{"segment_id": "a", "media_in": 0, "media_out": 10}]
        result = compare_fullcut_edls(
            edl, edl, fullcut_review={"quality": "BETTER", "verified": True},
        )
        self.assertFalse(result["has_edit"])
        self.assertEqual(result["duration_delta_sec"], 0)
        self.assertTrue(result["untrusted_external_review_ignored"])
        self.assertFalse(result["authorizes_promote_best"])

    def test_trim_has_negative_cost_but_not_automatic_quality_gain(self):
        baseline = [{"segment_id": "a", "media_in": 0, "media_out": 30}]
        candidate = [{"segment_id": "a", "media_in": 0, "media_out": 12}]
        result = compare_fullcut_edls(baseline, candidate)
        self.assertEqual(result["duration_delta_sec"], -18)
        self.assertEqual(result["pacing_gain"], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
