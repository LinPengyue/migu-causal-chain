"""V3 synthetic integration regression (NOT the actual A/B 79/65 acceptance run)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from .pipeline import V3InputError, run_structure
from .gate import review_evidence


def _events(path: Path, mid: str, scores) -> None:
    rows = []
    for i, score in enumerate(scores):
        t = 100.0 + 100.0 * i
        rows.append({
            "event_id": f"event_{i:06d}",
            "event_type": "Pass",
            "media_time": {"start_time_sec": t, "end_time_sec": t + 1,
                           "event_time_sec": t},
            "attributes": {"Score_Recognition": [f"{score[0]}:{score[1]}"]},
            "video_context": {"broadcast_phase": "LIVE", "is_replay": False},
        })
    path.write_text(json.dumps({
        "match_id": mid, "teams": {
            "team_1": {"name": "LeftFC"}, "team_2": {"name": "RightFC"}},
        "events": rows,
    }, ensure_ascii=False), encoding="utf-8")


def _strips(path: Path, mid: str, count: int = 4) -> None:
    chains = []
    for i in range(count):
        t = 100 + 15 * i
        chains.append({
            "clip_id": f"clip_{i}",
            "t0_ms": t * 1000, "t1_ms": (t + 5) * 1000,
            "pred_chain_template_id": "T_test",
            "pred_chain_label_zh": "射门机会",
            "chain_category": "danger",
            "prob_top1": 0.5 + i / (count * 4),
            "event_ids": [f"event_{i % 4:06d}"],
            "events": [{"event_id": f"event_{i % 4:06d}",
                        "type": "射门", "t_ms": t * 1000}],
        })
    path.write_text(json.dumps({
        "match_id": mid, "mode": "reinfer_A_original",
        "config": {"event_source": "raw_events", "pipeline": "algo_strip_prediction"},
        "chains": chains,
    }), encoding="utf-8")


class TestV3Synthetic(unittest.TestCase):
    def _run(self, td: Path, scores, match_id="match_A"):
        video = td / "video.mp4"
        video.write_bytes(b"synthetic_source")
        events = td / "raw_events.json"
        strips = td / "strip_A_original.json"
        _events(events, match_id, scores)
        _strips(strips, match_id)
        run = td / "v3" / "run1"
        report = run_structure(match_id=match_id, events=events,
                               predicted_strips=strips, video=video, out_dir=run)
        return report, run

    def test_left_a_story_plan_and_three_goal_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, run = self._run(Path(tmp), [(0,0),(0,1),(1,1),(2,1)])
            self.assertEqual(report["n_predictions"], 4)
            self.assertEqual(report["selected_arc_side"], "left")
            self.assertEqual(report["n_video_verified_goals"], 0)
            self.assertFalse(report["render_ready"])
            self.assertTrue((run / "story_plan.json").exists())
            self.assertTrue((run / "story_graph.json").exists())
            pred = json.loads((run / "predicted_causal.json").read_text())
            self.assertEqual(len(pred["causal_chains"]), 4)
            self.assertTrue(all(x["prediction_source"] == "causal_chain6_predicted"
                                and x["verification_status"] == "unverified"
                                and x["goal_action_sec"] is None
                                for x in pred["causal_chains"]))
            edl = json.loads((run / "candidate_edl.json").read_text())
            goals = [x for x in edl if x.get("critical_goal_role")]
            self.assertEqual(len(goals), 3)
            self.assertTrue(all(g["goal_action_sec"] is None
                                and g["media_in"] is None
                                and not g["include_in_cut"] for g in goals))

    def test_b_selects_right_last_arc_not_left_earlier_arc(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, run = self._run(Path(tmp),
                [(0,0),(0,1),(1,1),(2,1),(2,2),(2,3)], "match_B")
            self.assertEqual(report["selected_arc_side"], "right")
            story = json.loads((run / "story_view.json").read_text())
            self.assertEqual(story["protagonist_side"], "right")
            plan = json.loads((run / "story_plan.json").read_text())
            self.assertEqual(plan["protagonist"]["side"], "right")
            self.assertFalse(plan["render_ready"])

    def test_disallow_v2_output_and_existing_nonempty_v3(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "video.mp4"
            video.write_bytes(b"x")
            events = root / "raw_events.json"
            strips = root / "strip_A_original.json"
            _events(events, "m", [(0,0),(0,1),(1,1),(2,1)])
            _strips(strips, "m")
            with self.assertRaises(V3InputError):
                run_structure(match_id="m", events=events,
                              predicted_strips=strips, video=video,
                              out_dir=root / "v2" / "run")
            report = run_structure(match_id="m", events=events,
                predicted_strips=strips, video=video, out_dir=root / "v3" / "run")
            self.assertFalse(report["render_ready"])
            with self.assertRaises(V3InputError):
                run_structure(match_id="m", events=events,
                    predicted_strips=strips, video=video, out_dir=root / "v3" / "run")

    def test_reject_gold_and_match_leakage(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            video = td / "video.mp4"
            video.write_bytes(b"x")
            events = td / "events.json"
            _events(events, "A", [(0,0),(0,1),(1,1),(2,1)])
            strips = td / "strips.json"
            _strips(strips, "B")
            with self.assertRaises(V3InputError):
                run_structure(match_id="A", events=events,
                              predicted_strips=strips, video=video,
                              out_dir=td / "v3" / "mismatch")
            _strips(strips, "A")
            data = json.loads(strips.read_text())
            data["mode"] = "gold_clips"
            strips.write_text(json.dumps(data))
            with self.assertRaises(V3InputError):
                run_structure(match_id="A", events=events,
                              predicted_strips=strips, video=video,
                              out_dir=td / "v3" / "gold")

    def test_v2_gate_rejects_status_only_scoreboard_and_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            _, run = self._run(td, [(0,0),(0,1),(1,1),(2,1)])
            pack = td / "pack.json"
            pack.write_text(json.dumps({"goals": [
                {"role": "opening_deficit", "verification_status": "verified_first_live",
                 "live_or_replay": "replay", "observed_shot": True, "observed_net": True},
                {"role": "equalizer", "verification_status": "video_verified",
                 "live_or_replay": "live", "scoreboard_only": True},
            ]}))
            result = review_evidence(v3_run_dir=run, evidence_pack=pack,
                                     output_dir=td / "v3" / "verification")
            self.assertEqual(result["n_video_verified"], 0)
            self.assertEqual(result["status"], "blocked_missing_goal_evidence")
            self.assertFalse(result["render_ready"])
            edl = json.loads((td / "v3" / "verification" / "verified_candidate_edl.json").read_text())
            self.assertEqual(sum(1 for x in edl if x.get("verification_level") == "video_verified"), 0)


if __name__ == "__main__":
    unittest.main()
