"""Contract tests for formal 3-input full E2E (no Phase5 reuse)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_video_agent_v3.closed_loop_cli import _adapt_v1
from story_video_agent_v3.story_full_e2e_cli import main, validate_inputs


class FullE2EContractTests(unittest.TestCase):
    def test_rejects_phase5_and_enriched_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mp4 = root / "match.mp4"
            ev = root / "events_enriched.json"
            causal = root / "match_causal.json"
            mp4.write_bytes(b"\x00")
            ev.write_text("{}", encoding="utf-8")
            causal.write_text('{"causal_chains":[]}', encoding="utf-8")

            class Args:
                source_mp4 = mp4
                events_json = ev
                causal_json = causal
                out_dir = root / "out"
                phase5_dir = root / "04_phase5"
                baseline_edl = None

            errs = validate_inputs(Args())
            self.assertTrue(any("phase5" in e or "forbidden" in e for e in errs))
            self.assertTrue(any("enriched" in e for e in errs))

    def test_cli_requires_three_files(self):
        rc = main(["--help"]) if False else None
        # Missing args → SystemExit from argparse
        with self.assertRaises(SystemExit):
            main([])

    def test_adapt_v1_enables_goal_recovery_path(self):
        """Closed-loop V1 adapt must call Goal Recovery (not recovered_goals=None)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            events = root / "events_enriched.json"
            out = root / "predicted_causal.json"
            recovery = root / "goal_recovery.json"
            events.write_text(
                json.dumps({"events": [], "teams": {"team_1": {"name": "A"}, "team_2": {"name": "B"}}}),
                encoding="utf-8",
            )
            strip = {"chains": [], "n_chains": 0, "n_events": 0, "category_counts": {}}
            doc = _adapt_v1(
                strip=strip,
                enriched_events=events,
                match_id="unit_adapt",
                video_name="unit.mp4",
                out_path=out,
                recovery_out_path=recovery,
            )
            adapter = doc.get("v3_adapter") or {}
            self.assertTrue(adapter.get("goal_recovery_used"))
            self.assertTrue(recovery.is_file())
            self.assertIn("goal_recovery", adapter.get("prediction_source") or "")


if __name__ == "__main__":
    unittest.main()
