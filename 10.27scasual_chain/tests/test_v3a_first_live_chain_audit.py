"""Zero-cost tests for first-live chain audit mapping and recovery impact."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_video_agent_v3.first_live_chain_audit import (
    build_goal_recovery_impact,
    is_goal_action_segment,
    map_semantic_to_first_live_status,
)
from story_video_agent_v3.story_full_e2e_cli import evaluate_stages


class FirstLiveStatusMappingTests(unittest.TestCase):
    def test_ffmpeg_ok_never_verified(self):
        st = map_semantic_to_first_live_status(
            semantic_label="unresolved",
            candidate_extracted_ok=True,
            agent_auto_verified=False,
            goal_action_verified_ok=False,
        )
        self.assertEqual(st, "UNRESOLVED")

    def test_replay_maps(self):
        self.assertEqual(
            map_semantic_to_first_live_status(semantic_label="replay"),
            "REPLAY_DETECTED",
        )

    def test_possible_maps(self):
        self.assertEqual(
            map_semantic_to_first_live_status(semantic_label="possible_first_live"),
            "POSSIBLE_FIRST_LIVE",
        )

    def test_verified_requires_agent_auto_and_ok(self):
        self.assertEqual(
            map_semantic_to_first_live_status(
                semantic_label="verified_first_live",
                agent_auto_verified=False,
                goal_action_verified_ok=True,
            ),
            "UNRESOLVED",
        )
        self.assertEqual(
            map_semantic_to_first_live_status(
                semantic_label="verified_first_live",
                agent_auto_verified=True,
                goal_action_verified_ok=True,
            ),
            "FIRST_LIVE_VERIFIED",
        )

    def test_score_confirm_collision_unresolved(self):
        self.assertEqual(
            map_semantic_to_first_live_status(
                semantic_label="possible_first_live",
                score_confirm_collision=True,
            ),
            "UNRESOLVED",
        )

    def test_goal_action_segment_filter(self):
        self.assertTrue(is_goal_action_segment({"segment_id": "seg_equalizer_goal_action", "role": "equalizer_goal_action"}))
        self.assertFalse(is_goal_action_segment({"segment_id": "seg_equalizer_scoreboard", "role": "equalizer_scoreboard_anchor"}))


class GoalRecoveryImpactTests(unittest.TestCase):
    def test_entered_predicted_causal_from_outcome_chains(self):
        predicted = {
            "causal_chains": [
                {
                    "annotation_id": "v3_outcome_0001",
                    "prediction_source": "v3_goal_recovery+optional_8.31_antecedent",
                    "causal_chain_subtype": "V3进球恢复链",
                    "events": [
                        {
                            "event_id": "v3_goal_c1",
                            "type": "进球",
                            "t_ms": 1000000,
                            "source": "v3_goal_recovery",
                        }
                    ],
                }
            ],
            "v3_adapter": {
                "goal_recovery_used": True,
                "n_v3_outcome_chains": 1,
                "n_goal_terminals_in_adapted_chains": 1,
            },
        }
        recovery = {
            "n_candidates": 2,
            "n_single_goal": 1,
            "n_with_goal_action_sec": 1,
            "candidates": [
                {
                    "candidate_id": "c1",
                    "single_goal_increment": True,
                    "goal_action_sec": 1000.0,
                    "score_confirmation_sec": 1050.0,
                    "score_before": [0, 0],
                    "score_after": [1, 0],
                }
            ],
        }
        impact = build_goal_recovery_impact(predicted_causal=predicted, goal_recovery=recovery)
        self.assertTrue(impact["entered_predicted_causal"])
        self.assertEqual(impact["n_recovery_sourced_goal_events"], 1)
        self.assertTrue(impact["candidates_with_action"][0]["action_neq_confirm"])


class StageValidityTests(unittest.TestCase):
    def test_empty_files_not_valid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fresh = root / "01_to_04_fresh_v3r"
            for rel in (
                "01_enrich/events_enriched.json",
                "02_strip831/strip_A_original.json",
                "03_v1_adapt/predicted_causal.json",
                "03_v1_adapt/predicted_causal_live_goals_only.json",
                "03_v1_adapt/goal_recovery.json",
                "04_phase5/candidate_edl.json",
                "04_phase5/story_clean.mp4",
                "05_live_audit/goal_live_audit.json",
                "05_live_audit/first_live_visual_audit.json",
            ):
                p = fresh / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                if rel.endswith(".mp4"):
                    p.write_bytes(b"tiny")
                else:
                    p.write_text("{}", encoding="utf-8")
            (root / "99_final").mkdir(parents=True, exist_ok=True)
            (root / "99_final" / "delivery_status.json").write_text(
                json.dumps({"delivery_status": "BLOCKED", "release_authorized": False}),
                encoding="utf-8",
            )
            ev = evaluate_stages(out_dir=root, fresh_root=fresh, delivery={"delivery_status": "BLOCKED"})
            self.assertFalse(ev["all_required_valid"])
            self.assertTrue(ev["blocking_errors"])


if __name__ == "__main__":
    unittest.main()
