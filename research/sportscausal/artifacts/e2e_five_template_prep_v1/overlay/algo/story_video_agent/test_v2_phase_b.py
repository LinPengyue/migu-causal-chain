"""Phase B unit tests (mock only)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent.api_provider import ApiProvider
from story_video_agent.v2_coverage import SearchCoverage
from story_video_agent.v2_evidence_schema import dedupe_evidence_items, empty_evidence_item, items_from_observation
from story_video_agent.v2_phase_b_runner import compare_paths
from story_video_agent.v2_phase_b_toolbox import V2PhaseBToolbox


class TestEvidenceDedup(unittest.TestCase):
    def test_dedupe_same_bin_role(self):
        a = empty_evidence_item(
            narrative_role="scoreboard",
            media_start=10.0,
            media_end=20.0,
            frame_ids=["f1"],
            supporting_observations=["score 1-0"],
        )
        b = empty_evidence_item(
            narrative_role="scoreboard",
            media_start=12.0,
            media_end=25.0,
            frame_ids=["f2"],
            supporting_observations=["scoreboard visible"],
        )
        out = dedupe_evidence_items([a, b], time_bin_sec=30.0)
        self.assertEqual(len(out), 1)
        self.assertEqual(set(out[0]["frame_ids"]), {"f1", "f2"})

    def test_items_from_observation_not_per_action(self):
        obs = {
            "media_start_sec": 0,
            "media_end_sec": 10,
            "perception": {
                "normalized_ok": True,
                "observed_actions": ["a", "b", "c", "scoreboard 2-1"],
                "frame_ids": ["f0"],
            },
        }
        items = items_from_observation(obs, tool="global_overview")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["narrative_role"], "scoreboard")


class TestCoverage(unittest.TestCase):
    def test_partition_untouched(self):
        cov = SearchCoverage(duration_sec=1200, partition_sec=600)
        cov.add(
            tool="partition_scan",
            requested_start=0,
            requested_end=600,
            sampled_times=[100, 300],
            observed=True,
        )
        parts = cov.partition_coverage()
        self.assertEqual(parts[0]["status"], "observed")
        self.assertEqual(parts[1]["status"], "untouched")

    def test_overview_does_not_observe_all_partitions(self):
        cov = SearchCoverage(duration_sec=1200, partition_sec=600)
        cov.add(
            tool="global_overview",
            requested_start=0,
            requested_end=1200,
            sampled_times=[100, 700],
            observed=True,
        )
        parts = cov.partition_coverage()
        self.assertEqual(parts[0]["status"], "overview_sparse_only")
        self.assertEqual(parts[1]["status"], "overview_sparse_only")
        self.assertEqual(cov.summary()["partitions_observed"], 0)


class TestToolboxBounds(unittest.TestCase):
    def test_partition_span(self):
        class _S:
            budget = type("B", (), {"remaining": 10})()

        tb = V2PhaseBToolbox(duration=8000.0, store=_S(), vision=object())  # type: ignore[arg-type]
        with self.assertRaises(Exception):
            tb.normalize_arguments("partition_scan", {"start": 0, "end": 30})
        ok = tb.normalize_arguments("partition_scan", {"start": 0, "end": 600})
        self.assertEqual(ok["start"], 0.0)


class TestRunnerMock(unittest.TestCase):
    def test_compare_seg_or_clip(self):
        video = Path("/tmp/migu_vd_clips/croatia_seg15m_a.mp4")
        if not video.is_file():
            video = Path("/tmp/migu_vd_clips/croatia_2_1_60s.mp4")
        if not video.is_file():
            self.skipTest("no clip")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)

            def factory():
                return ApiProvider(force_mock=True, require_real=False)

            cmp = compare_paths(
                video=video,
                out_dir=out,
                api_factory=factory,
                max_steps=3,
                frame_budget_multi=12,
                partition_sec=300.0,
                use_llm_planner=True,
            )
            self.assertIn("path_a_fixed_matched", cmp)
            self.assertIn("path_b_multi", cmp)
            self.assertTrue((out / "path_b_multi" / "story_discovery.json").is_file())
            self.assertTrue((out / "path_b_multi" / "search_coverage.json").is_file())
            a = json.loads((out / "path_a_fixed_matched" / "agent_trace.json").read_text())
            b = json.loads((out / "path_b_multi" / "agent_trace.json").read_text())
            # matched frames: fixed uses multi frames_used
            self.assertEqual(a["frames_used"], b["frames_used"])


if __name__ == "__main__":
    unittest.main()
