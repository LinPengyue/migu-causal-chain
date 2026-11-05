"""Zero-API integration tests for fresh V3-R -> V3-A orchestration."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_video_agent_v3.fresh_e2e_cli import (
    compare_history, edl_rows, historical_trace, run_fresh_e2e, validate_render_rows,
)


def dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


class FreshE2ETests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sources = {}
        for key in ("events", "causal_atoms", "video"):
            path = self.root / f"input_{key}.json"
            path.write_text("{}", encoding="utf-8")
            self.sources[key] = path
        self.out = self.root / "fresh"
        self.history = self.root / "history"
        dump(self.history / "01_enrich/enrich_report.json", {
            "source_events": str(self.sources["events"]),
            "source_causal_atoms_only": str(self.sources["causal_atoms"]),
        })
        dump(self.history / "04_phase5_p1_polish/candidate_edl.json", [{"segment_id": "old_polish"}])
        self.calls = []
        self.edl = [
            {"segment_id": "title", "role": "story_title", "include_in_cut": True,
             "media_in": None, "media_out": None},
            {"segment_id": "goal", "role": "opponent_opening_goal_action",
             "include_in_cut": True, "media_in": 10, "media_out": 20},
            {"segment_id": "retired", "role": "buildup", "include_in_cut": False,
             "media_in": 22, "media_out": 30},
        ]

    def fake_match(self, **kw):
        self.calls.append(("match", kw))
        out = kw["out_dir"]
        for rel in (
            "01_enrich/events_enriched.json", "02_strip831/strip_A_original.json",
            "03_v1_adapt/predicted_causal.json",
            "03_v1_adapt/predicted_causal_live_goals_only.json",
            "04_phase5/t01_story.json", "04_phase5/story_plan.json",
        ):
            dump(out / rel, {})
        dump(out / "04_phase5/candidate_edl.json", self.edl)
        (out / "04_phase5/story_clean.mp4").write_bytes(b"fake baseline")
        dump(out / "04_phase5/phase5_manifest.json", {"inputs": {
            "causal": str(out / "03_v1_adapt/predicted_causal_live_goals_only.json"),
            "events": str(out / "01_enrich/events_enriched.json"),
            "video": str(kw["video"]),
        }})
        return {"match_id": kw["match_id"]}

    def fake_agent(self, **kw):
        self.calls.append(("agent", kw))
        dump(kw["out_dir"] / "best_candidate_edl.json", self.edl)
        dump(kw["out_dir"] / "self_revise_summary.json", {"best_round": 0})
        return {"phase5_dir": str(kw["phase5_dir"]), "best_round": 0,
                "accepted_any_revision": False, "agent_claimed_success": False,
                "api_usage": {"http_attempts": 0}}

    def fake_render(self, **kw):
        self.calls.append(("render", kw))
        self.assertEqual([r["segment_id"] for r in kw["delivery_edl"]], ["title", "goal"])
        for name in ("story_clean.mp4", "story_qc.mp4"):
            (kw["out_dir"] / name).write_bytes(b"fake candidate")
        return {"clean": {"out_mp4": str(kw["out_dir"] / "story_clean.mp4")}}

    def run_fake(self):
        with patch("story_video_agent_v3.closed_loop_cli.run_match", side_effect=self.fake_match), \
             patch("story_video_agent_v3.self_revise_agent.run_self_revise", side_effect=self.fake_agent), \
             patch("story_video_agent.phase5_delivery.render_dual_delivery", side_effect=self.fake_render), \
             patch("story_video_agent_v3.self_revise_agent.find_duplicate_goal_cuts", return_value=[]):
            return run_fresh_e2e(match_id="A_uae_oman", events=self.sources["events"],
                                 causal_atoms=self.sources["causal_atoms"],
                                 video=self.sources["video"], out_dir=self.out,
                                 algo_root=self.root, history_root=self.history)

    def test_fresh_run_wires_only_new_outputs(self):
        result = self.run_fake()
        self.assertEqual(result["status"], "completed_candidate_only")
        self.assertFalse(result["render_ready"])
        self.assertEqual([x[0] for x in self.calls], ["match", "agent", "render"])
        agent = self.calls[1][1]
        self.assertFalse(agent["prefer_p1_polish"])
        self.assertIsNone(agent["stage2_proposal"])
        self.assertIsNone(agent["audit_path"])
        self.assertFalse(agent["enable_real_api"])
        self.assertTrue(agent["allow_degraded_offline"])
        self.assertEqual(agent["predicted_causal"],
                         self.out / "01_to_04_fresh_v3r/03_v1_adapt/predicted_causal_live_goals_only.json")
        self.assertTrue(result["lineage"]["v3a_video"]["exists"])
        self.assertIsNone(result["historical_comparison"]["files"]["polish_edl_reference_only"]["fresh"])
        self.assertTrue((self.history / "04_phase5_p1_polish/candidate_edl.json").exists())

    def test_nonempty_output_rejected(self):
        self.out.mkdir()
        (self.out / "old.json").write_text("x")
        with self.assertRaises(FileExistsError):
            self.run_fake()

    def test_api_requires_explicit_double_approval(self):
        with self.assertRaises(ValueError):
            run_fresh_e2e(match_id="A", events=self.sources["events"],
                          causal_atoms=self.sources["causal_atoms"], video=self.sources["video"],
                          out_dir=self.out, algo_root=self.root,
                          enable_real_api=True, i_approve_budget=False)

    def test_explicit_replay_rejected(self):
        with patch("story_video_agent_v3.self_revise_agent.find_duplicate_goal_cuts", return_value=[]):
            with self.assertRaisesRegex(ValueError, "replay"):
                validate_render_rows([{"segment_id": "bad", "role": "goal_action",
                                       "is_replay": True, "media_in": 1, "media_out": 3}])

    def test_history_is_read_only_reference(self):
        trace = historical_trace(self.history, self.sources)
        self.assertTrue(trace["historical_sources"]["events"]["same_as_requested"])
        self.assertTrue(trace["read_only"])
        self.assertIsNone(compare_history(self.out, self.history)["files"]["polish_edl_reference_only"]["fresh"])


if __name__ == "__main__":
    unittest.main()
