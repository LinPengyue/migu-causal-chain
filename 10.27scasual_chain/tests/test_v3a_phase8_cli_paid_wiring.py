"""Phase8 CLI wiring: real-API must not stick in offline/skip_vlm; multi-round flag."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.story_e2e_cli import build_parser, resolve_cli_mode


class TestPhase8CliPaidWiring(unittest.TestCase):
    def test_enable_real_api_clears_skip_vlm_even_if_offline_default_absent(self):
        p = build_parser()
        ns = p.parse_args(
            [
                "--match-json",
                "/tmp/m.json",
                "--source-mp4",
                "/tmp/m.mp4",
                "--out-dir",
                "/tmp/o",
                "--enable-real-api",
                "--i-approve-budget",
            ]
        )
        self.assertFalse(ns.offline)  # default False (fixed sticky True bug)
        skip_vlm, enable_real, notes = resolve_cli_mode(ns)
        self.assertTrue(enable_real)
        self.assertFalse(skip_vlm)
        self.assertFalse(notes["skip_vlm"])

    def test_enable_real_api_overrides_conflicting_offline_flag(self):
        p = build_parser()
        ns = p.parse_args(
            [
                "--match-json",
                "/tmp/m.json",
                "--source-mp4",
                "/tmp/m.mp4",
                "--out-dir",
                "/tmp/o",
                "--offline",
                "--enable-real-api",
            ]
        )
        skip_vlm, enable_real, notes = resolve_cli_mode(ns)
        self.assertTrue(enable_real)
        self.assertFalse(skip_vlm)
        self.assertEqual(notes.get("conflict"), "enable_real_api_overrides_offline_flag")

    def test_without_real_api_skip_vlm_true(self):
        p = build_parser()
        ns = p.parse_args(
            [
                "--match-json",
                "/tmp/m.json",
                "--source-mp4",
                "/tmp/m.mp4",
                "--out-dir",
                "/tmp/o",
            ]
        )
        skip_vlm, enable_real, _ = resolve_cli_mode(ns)
        self.assertFalse(enable_real)
        self.assertTrue(skip_vlm)

    def test_phase8_paid_multi_round_flag_exposed(self):
        p = build_parser()
        ns = p.parse_args(
            [
                "--match-json",
                "/tmp/m.json",
                "--source-mp4",
                "/tmp/m.mp4",
                "--out-dir",
                "/tmp/o",
                "--enable-real-api",
                "--i-approve-budget",
                "--phase8-paid-multi-round",
                "--max-rounds",
                "3",
                "--first-live-evidence-dir",
                "/tmp/evidence",
            ]
        )
        self.assertTrue(ns.phase8_paid_multi_round)
        self.assertEqual(ns.max_rounds, 3)
        self.assertEqual(Path(ns.first_live_evidence_dir), Path("/tmp/evidence"))

    def test_phase8_paid_multi_round_default_false(self):
        p = build_parser()
        ns = p.parse_args(
            [
                "--match-json",
                "/tmp/m.json",
                "--source-mp4",
                "/tmp/m.mp4",
                "--out-dir",
                "/tmp/o",
            ]
        )
        self.assertFalse(ns.phase8_paid_multi_round)


if __name__ == "__main__":
    unittest.main()
