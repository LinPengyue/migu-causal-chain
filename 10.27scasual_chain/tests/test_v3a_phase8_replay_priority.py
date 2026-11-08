"""Phase8 safety: a replay hit must never be overruled by a positive review."""
import unittest

from story_video_agent_v3.first_live_window_evidence import (
    REPLAY_CONFIRMED,
    build_broadcast_timeline_review,
    validate_first_live_evidence_record,
)


class TestReplayReviewPriority(unittest.TestCase):
    def test_conflicting_explicit_first_live_cannot_override_replay(self):
        source_sha = "test_source_sha"
        review = build_broadcast_timeline_review(
            source_sha=source_sha,
            pts_start=824.81,
            pts_end=835.15,
            events=[{
                "event_id": "replay_event",
                "media_time": {"start_time_sec": 824.81, "end_time_sec": 835.15},
                "video_context": {"broadcast_phase": "REPLAY", "is_replay": True},
            }],
            explicit_review={
                "source_sha256": source_sha,
                "source_pts_start": 824.81,
                "source_pts_end": 835.15,
                "outcome": "FIRST_LIVE_VERIFIED",
                "reviewer": "test_reviewer",
                "rationale": "contradictory positive claim",
                "evidence_refs": [{"kind": "context_clip", "sha256": "a" * 64}],
            },
        )
        self.assertEqual(review["outcome"], REPLAY_CONFIRMED)
        self.assertIn("explicit_review_cannot_override_replay_hits", review["rationale"])

    def test_external_positive_review_with_replay_hits_not_certified(self):
        review = {
            "schema": "v3a_broadcast_timeline_review_v1",
            "source_sha256": "test_sha",
            "source_pts_start": 10.0,
            "source_pts_end": 20.0,
            "outcome": "FIRST_LIVE_VERIFIED",
            "method": "claimed_review",
            "replay_hits": [{"event_id": "r1", "is_replay": True}],
        }
        checked = validate_first_live_evidence_record(
            None,
            source_sha="test_sha",
            pts_start=10.0,
            pts_end=20.0,
            timeline_review=review,
            require_files_exist=False,
        )
        self.assertFalse(checked["first_live_verified"])
        self.assertTrue(checked["replay_confirmed"])
        self.assertFalse(checked["ok"])


if __name__ == "__main__":
    unittest.main()
