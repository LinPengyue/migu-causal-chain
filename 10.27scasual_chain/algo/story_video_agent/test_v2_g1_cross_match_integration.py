"""G1 integration tests — exercise real CLI/composer entrypoints (zero API)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent.v2_g0_cross_match_preflight import (
    assert_verify_cache_entry,
    build_strip_provenance,
    validate_strip_bundle_provenance,
)
from story_video_agent.v2_g1_cross_match_cli import main as g1_main, run_g1_dry
from story_video_agent.v2_generic_edl_composer import (
    compose_generic_t01_edl,
    refuse_croatia_edl_builder,
    GenericEdlError,
)
from story_video_agent.v2_score_transitions import analyze_last_deficit_arcs
from story_video_agent.v2_strip_guided_r2_3_cli import main as r23_main


def _write_events(path: Path, match_id: str, scores, teams=None) -> None:
    events = []
    t = 100.0
    for i, (a, b) in enumerate(scores):
        events.append(
            {
                "event_id": f"event_{i:06d}",
                "event_type": "Pass",
                "media_time": {
                    "start_time_sec": t,
                    "end_time_sec": t + 1,
                    "event_time_sec": t,
                },
                "attributes": {"Score_Recognition": [f"{a}:{b}"]},
                "video_context": {"broadcast_phase": "LIVE", "is_replay": False},
            }
        )
        t += 100.0
    obj = {
        "match_id": match_id,
        "schema_version": "test",
        "teams": teams
        or {
            "team_1": {"name": "LeftFC", "color": "白"},
            "team_2": {"name": "RightFC", "color": "蓝"},
        },
        "events": events,
    }
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _tiny_video(path: Path) -> None:
    path.write_bytes(b"FAKEMP4" + b"\x00" * 64)


class TestLastDeficitArc(unittest.TestCase):
    def test_b_selects_right_last_arc(self):
        timeline = [
            {"score": s, "left": s[0], "right": s[1], "media_start_sec": float(i)}
            for i, s in enumerate([(0, 0), (0, 1), (1, 1), (2, 1), (2, 2), (2, 3)])
        ]
        out = analyze_last_deficit_arcs(
            timeline, team_names={"team_1": "奥萨苏纳", "team_2": "塞尔塔维戈"}
        )
        self.assertEqual(out["status"], "story_candidate")
        sel = out["selected_arc"]
        self.assertEqual(sel["protagonist_side"], "right")
        self.assertEqual(sel["protagonist_team_name"], "塞尔塔维戈")
        self.assertEqual(sel["deficit_score"], [2, 1])
        self.assertEqual(sel["equalizer_score"], [2, 2])
        self.assertEqual(sel["go_ahead_score"], [2, 3])
        # Left first arc must be abandoned, not selected
        self.assertTrue(any(a.get("protagonist_side") == "left" and a.get("complete") for a in out["all_arcs"]))
        self.assertNotEqual(sel.get("go_ahead_score"), [2, 1])

    def test_a_selects_left(self):
        timeline = [
            {"score": s, "left": s[0], "right": s[1], "media_start_sec": float(i)}
            for i, s in enumerate([(0, 0), (0, 1), (1, 1), (2, 1)])
        ]
        out = analyze_last_deficit_arcs(timeline, team_names={"team_1": "阿联酋", "team_2": "阿曼"})
        self.assertEqual(out["selected_arc"]["protagonist_side"], "left")
        self.assertEqual(out["selected_arc"]["protagonist_team_name"], "阿联酋")

    def test_no_comeback(self):
        timeline = [
            {"score": s, "left": s[0], "right": s[1], "media_start_sec": float(i)}
            for i, s in enumerate([(1, 0), (2, 0), (3, 0)])
        ]
        out = analyze_last_deficit_arcs(timeline)
        self.assertIn(out["status"], ("no_comeback", "partial_story", "unresolved"))
        self.assertIsNone(out.get("selected_arc"))


class TestGenericEdl(unittest.TestCase):
    def test_structure_only_three_goals_unresolved(self):
        arc = {
            "protagonist_side": "left",
            "protagonist_team_name": "阿联酋",
            "deficit_score": [0, 1],
            "equalizer_score": [1, 1],
            "go_ahead_score": [2, 1],
            "score_confirmation_sec": {"deficit": 100.0, "equalizer": 200.0, "go_ahead": 300.0},
            "goal_action_sec": {"deficit": None, "equalizer": None, "go_ahead": None},
        }
        edl = compose_generic_t01_edl(
            match_id="A",
            selected_arc=arc,
            arc_status="story_candidate",
            team_names={"team_1": "阿联酋", "team_2": "阿曼"},
            level="structure_only",
        )
        self.assertFalse(edl["render_ready"])
        self.assertFalse(edl["verified_first_live"])
        self.assertFalse(edl["all_five_goals_verified_first_live"])
        roles = [s["role"] for s in edl["segments"] if s["role"] != "title_card"]
        self.assertEqual(roles, ["opening_deficit", "equalizer", "go_ahead"])
        self.assertTrue(all(s.get("verification_status") == "unresolved" for s in edl["segments"] if s["role"] != "title_card"))

    def test_refuse_croatia_builder_for_other_match(self):
        with self.assertRaises(GenericEdlError):
            refuse_croatia_edl_builder("v2_strip_guided_r2_6_build_edl", match_id="阿联酋VS阿曼")

    def test_no_comeback_empty_edl(self):
        edl = compose_generic_t01_edl(
            match_id="N", selected_arc=None, arc_status="no_comeback", level="structure_only"
        )
        self.assertEqual(edl["segments"], [])
        self.assertFalse(edl["render_ready"])

    def test_video_verified_rejects_out_of_range_or_fake_status(self):
        """Status-only / OOR claims must fail closed (unresolved), not upgrade."""
        arc = {
            "protagonist_side": "left",
            "deficit_score": [0, 1],
            "equalizer_score": [1, 1],
            "go_ahead_score": [2, 1],
            "score_confirmation_sec": {"deficit": 1, "equalizer": 2, "go_ahead": 3},
            "goal_action_sec": {},
        }
        goals = [
            {
                "role": "opening_deficit",
                "verification_status": "verified_first_live",
                "shot_sec": 10,
                "net_sec": 12,
                "live_or_replay": "live",
                "media_in": 5,
                "media_out": 99999,
            }
        ]
        edl = compose_generic_t01_edl(
            match_id="X",
            selected_arc=arc,
            arc_status="story_candidate",
            goals=goals,
            video_duration_sec=100.0,
            level="video_verified",
            expected_identity={
                "match_id": "X",
                "video_sha256": "v",
                "events_sha256": "e",
                "strip_provenance": "s",
            },
        )
        segs = [s for s in edl["segments"] if s.get("role") == "opening_deficit"]
        self.assertTrue(segs)
        self.assertEqual(segs[0].get("verification_status"), "unresolved")
        self.assertFalse(edl.get("verified_first_live"))
        self.assertFalse(edl["render_ready"])


class TestG1CliGates(unittest.TestCase):
    def test_rejects_causal_filename(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            video = td / "v.mp4"
            _tiny_video(video)
            events = td / "match_causal.json"
            _write_events(events, "match_A", [(0, 0), (0, 1), (1, 1), (2, 1)])
            out = td / "out"
            rc = g1_main(
                [
                    "--match-id",
                    "match_A",
                    "--video",
                    str(video),
                    "--events",
                    str(events),
                    "--out-dir",
                    str(out),
                    "--skip-strip-reinfer",
                ]
            )
            self.assertEqual(rc, 2)
            report = json.loads((out / "cli_report.json").read_text(encoding="utf-8"))
            self.assertTrue(str(report["status"]).startswith("aborted"))
            self.assertFalse(report["render_ready"])

    def test_rejects_match_id_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            video = td / "v.mp4"
            _tiny_video(video)
            events = td / "events.json"
            _write_events(events, "match_A", [(0, 0), (0, 1), (1, 1), (2, 1)])
            out = td / "out"
            rc = g1_main(
                [
                    "--match-id",
                    "match_B",
                    "--video",
                    str(video),
                    "--events",
                    str(events),
                    "--out-dir",
                    str(out),
                    "--skip-strip-reinfer",
                ]
            )
            self.assertEqual(rc, 2)

    def test_rejects_gold_strip_dump(self):
        bad = {"mode": "gold_clips", "config": {"event_source": "gold_events", "pipeline": "gold_clip"}, "chains": []}
        self.assertFalse(validate_strip_bundle_provenance(bad).get("ok"))

    def test_legacy_croatia_cache_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            vdir = td / "verify_event_1"
            vdir.mkdir()
            (vdir / "original_goal_verify.json").write_text("{}", encoding="utf-8")
            # no provenance.json
            out = assert_verify_cache_entry(
                expected={
                    "match_id": "A",
                    "video_sha256": "v",
                    "events_sha256": "e",
                    "strip_provenance": "s",
                },
                cache_dir=vdir,
                event_id="event_1",
            )
            self.assertFalse(out["ok"])
            self.assertEqual(out["reason"], "missing_provenance_fail_closed")

    def test_cache_mismatch_different_match(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            vdir = td / "verify_event_1"
            vdir.mkdir()
            (vdir / "original_goal_verify.json").write_text("{}", encoding="utf-8")
            (vdir / "provenance.json").write_text(
                json.dumps(
                    {
                        "match_id": "croatia",
                        "video_sha256": "vC",
                        "events_sha256": "eC",
                        "strip_provenance": "sC",
                        "event_id": "event_1",
                    }
                ),
                encoding="utf-8",
            )
            out = assert_verify_cache_entry(
                expected={
                    "match_id": "A",
                    "video_sha256": "vA",
                    "events_sha256": "eA",
                    "strip_provenance": "sA",
                },
                cache_dir=vdir,
                event_id="event_1",
            )
            self.assertFalse(out["ok"])

    def test_r23_refuses_default_croatia_r22_for_other_match(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            video = td / "v.mp4"
            _tiny_video(video)
            events = td / "events.json"
            _write_events(
                events,
                "10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语",
                [(0, 0), (0, 1), (1, 1), (2, 1)],
                teams={"team_1": {"name": "阿联酋"}, "team_2": {"name": "阿曼"}},
            )
            out = td / "out"
            rc = r23_main(
                [
                    "--video",
                    str(video),
                    "--events",
                    str(events),
                    "--out-dir",
                    str(out),
                    "--match-id",
                    "10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语",
                    "--skip-render",
                    "--no-llm-planner",
                    "--skip-fourth-goal-verify",
                ]
            )
            self.assertEqual(rc, 2)
            report = json.loads((out / "cli_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "aborted_croatia_default_r22_for_cross_match")
            self.assertFalse(report["render_ready"])

    def test_g1_dry_structure_a_like(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            video = td / "v.mp4"
            _tiny_video(video)
            events = td / "events.json"
            mid = "synthetic_uae_oman"
            _write_events(
                events,
                mid,
                [(0, 0), (0, 1), (1, 1), (2, 1)],
                teams={"team_1": {"name": "阿联酋"}, "team_2": {"name": "阿曼"}},
            )
            out = td / "out"
            report = run_g1_dry(
                match_id=mid,
                video=video,
                events=events,
                out_dir=out,
                skip_strip_reinfer=True,
            )
            self.assertEqual(report["status"], "ok_structure_dry_run")
            self.assertEqual(report["protagonist_side"], "left")
            self.assertEqual(report["n_video_verified_goals"], 0)
            self.assertFalse(report["render_ready"])
            edl = json.loads((out / "candidate_edl.json").read_text(encoding="utf-8"))
            self.assertEqual(edl["level"], "structure_only")
            self.assertFalse(edl["verified_first_live"])

    def test_strip_provenance_rejects_gold_mode(self):
        with self.assertRaises(ValueError):
            build_strip_provenance(
                run_id="r1",
                events_sha256="abc",
                algo_root="/x",
                algo_version="1",
                prediction_mode="gold_clips",
            )


if __name__ == "__main__":
    unittest.main()
