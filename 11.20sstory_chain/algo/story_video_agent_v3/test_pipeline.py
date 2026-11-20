"""V3 synthetic integration regression (NOT the actual A/B 79/65 acceptance run)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from .pipeline import (
    V3InputError,
    run_structure,
    _candidate_buildup,
    to_predicted_causal,
)
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
    # Editorial 蓄力 anchor strictly between first deficit (~200) and equalizer (~300)
    rows.append({
        "event_id": "event_buildup_shot",
        "event_type": "Shot",
        "media_time": {"start_time_sec": 248.0, "end_time_sec": 252.0,
                       "event_time_sec": 250.0},
        "attributes": {},
        "video_context": {"broadcast_phase": "LIVE", "is_replay": False},
    })
    path.write_text(json.dumps({
        "match_id": mid, "teams": {
            "team_1": {"name": "LeftFC"}, "team_2": {"name": "RightFC"}},
        "events": rows,
    }, ensure_ascii=False), encoding="utf-8")


def _strips(path: Path, mid: str, count: int = 4) -> None:
    """Place strip windows across score timeline; include deficit→equalizer 蓄力 band.

    Synthetic scores use t=100+100*i, so first-deficit→equalizer is ~(200, 300).
    """
    chains = []
    # times chosen so at least one chain sits strictly inside (deficit, equalizer)
    times = [110, 220, 250, 280, 320][:count]
    if count > len(times):
        times = [100 + 20 * i for i in range(count)]
        times[min(1, count - 1)] = 220
    for i, t in enumerate(times):
        eid = f"event_{min(i, 3):06d}"
        # Map mid-window strips onto score-event ids that exist (event_000001 at t=200, etc.)
        if 200 < t < 300:
            eid = "event_buildup_shot"
            etype = "Shot"
            et_ms = 250000
        else:
            etype = "Pass"
            et_ms = int(t * 1000)
        chains.append({
            "clip_id": f"clip_{i}",
            "t0_ms": t * 1000, "t1_ms": (t + 5) * 1000,
            "pred_chain_template_id": "T_test",
            "pred_chain_label_zh": "射门机会",
            "chain_category": "danger",
            "prob_top1": 0.5 + i / (count * 4),
            "event_ids": [eid],
            "events": [{"event_id": eid, "type": etype, "t_ms": et_ms}],
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
            story = json.loads((run / "story_view.json").read_text())
            beats = (story.get("recognition") or {}).get("beats") or {}
            for beat in ("铺垫", "蓄力", "转折", "高潮", "收尾"):
                self.assertTrue(beats.get(beat), msg=f"missing beat {beat}")
            self.assertTrue(story.get("has_story"))
            comp = json.loads((run / "narrative_completeness_report.json").read_text())
            self.assertTrue(comp["role_coverage_complete"])
            self.assertFalse(comp["gates"]["critical_video_evidence_pass"])
            self.assertFalse(comp["render_ready"])
            # Goal narrative placeholders must not invent action times
            placeholders = [e for e in story["events"] if e.get("narrative_placeholder")]
            self.assertGreaterEqual(len(placeholders), 3)
            self.assertTrue(all(p.get("goal_action_sec") is None for p in placeholders
                                if p.get("critical_goal_role")))

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


    def test_buildup_uses_only_matching_raw_live_evidence(self):
        arc = {"score_confirmation_sec": {"deficit": 200.0, "equalizer": 300.0}}
        predicted = {"causal_chains": [{
            "chain_id": "p1", "t0_ms": 230000, "last_event": "shot",
            "first_event": "pass", "predicted_label": "射门机会",
            "confidence": 0.6,
            "events": [{"event_id": "action1", "type": "shot", "t_ms": 231000}],
        }]}
        raw_live = {"event_id": "action1", "event_type": "Shot",
                    "event_time_sec": 231.0, "broadcast_phase": "LIVE",
                    "is_replay": False}
        ok = _candidate_buildup(predicted, arc, allowed_events=[raw_live])
        self.assertEqual(len(ok), 1)
        self.assertEqual(ok[0]["verification_status"], "unverified")
        self.assertEqual(ok[0]["source_chain_id"], "p1")
        self.assertEqual(_candidate_buildup(predicted, arc,
            allowed_events=[{**raw_live, "is_replay": True}]), [])
        self.assertEqual(_candidate_buildup(predicted, arc,
            allowed_events=[{**raw_live, "event_time_sec": 240.0}]), [])
        self.assertEqual(_candidate_buildup(predicted, arc,
            allowed_events=[{**raw_live, "event_type": "Pass"}]), [])
        predicted["causal_chains"][0]["predicted_label"] = "进球"
        self.assertEqual(_candidate_buildup(predicted, arc,
            allowed_events=[raw_live]), [])

    def test_hydrate_events_from_source_ids_when_sequence_empty(self):
        """Real G1 strip_A_original has event_ids but empty embedded events."""
        adapted = {
            "n_dropped": 0,
            "chain_diagnostics": [],
            "chains": [{
                "strip_chain_id": "strip_clip00",
                "predicted_category": "special",
                "predicted_template_id": "T",
                "predicted_label": None,
                "first_event": "pass",
                "last_event": "pass",
                "t0_ms": 230000,
                "t1_ms": 240000,
                "source_event_ids": ["action1"],
                "event_sequence": [],
                "confidence": None,
                "confidence_field": None,
                "margin": None,
            }],
        }
        raw = [{
            "event_id": "action1",
            "event_type": "Shot",
            "event_time_sec": 231.0,
            "media_start_sec": 230.0,
            "media_end_sec": 232.0,
            "broadcast_phase": "LIVE",
            "is_replay": False,
        }]
        pred = to_predicted_causal(
            adapted,
            match_id="m",
            hashes={"events_sha256": "e", "strips_sha256": "s", "video_sha256": "v", "mode": "reinfer_A_original"},
            raw_events=raw,
        )
        self.assertEqual(pred["n_chains_hydrated_from_raw_ids"], 1)
        self.assertEqual(pred["n_chains_with_empty_events"], 0)
        chain = pred["causal_chains"][0]
        self.assertEqual(len(chain["events"]), 1)
        self.assertEqual(chain["events"][0]["type"], "Shot")
        self.assertEqual(chain["events"][0]["t_ms"], 231000)
        self.assertEqual(chain["events"][0]["mapping_status"], "hydrated_from_raw_event_ids")
        self.assertIsNone(chain["goal_action_sec"])
        arc = {"score_confirmation_sec": {"deficit": 200.0, "equalizer": 300.0}}
        buildup = _candidate_buildup(pred, arc, allowed_events=raw)
        self.assertEqual(len(buildup), 1)
        self.assertEqual(buildup[0]["event_id"], "action1")

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
