from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.story_phase10d_audit import assess_run, main


def _write(root: Path, name: str, obj: dict):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


class TestPhase10DAutonomyAudit(unittest.TestCase):
    def _setup(self, root: Path, *, fixture=False, rendered=True, real=True):
        prefix = "02_round_01/phase10_exploratory/"
        _write(root, "story_e2e_audit.json", {"status": "UNRESOLVED"})
        _write(root, prefix + "phase10d_provenance.json", {
            "fixture_used": fixture,
            "model_planner_called": real,
            "planner_ok": real,
            "planner_provider_mode": "real" if real else "mock",
            "real_model_proposal": real and not fixture,
            "model_selected_target": "seg_buildup_1" if real else None,
            "model_selected_action": "trim" if real else None,
            "candidate_rendered": rendered,
            "http_attempts_so_far": 2 if real else 0,
            "est_cost_usd_so_far": 0.006 if real else 0,
        })
        _write(root, prefix + "exploratory_trial.json", {
            "source": "FIXTURE" if fixture else "REAL_LLM",
            "candidate_rendered": rendered,
            "blind_pair_status": "BLIND_PAIR_READY" if rendered else "NO_CANDIDATE_PAIR",
            "status": "EXPLORATORY_RENDERED_NOT_VERIFIED" if rendered else "BLOCKED",
        })

    def test_real_proposal_and_render_is_not_quality_claim(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._setup(root)
            result = assess_run(root)
            self.assertEqual(result["autonomous_candidate_status"], "MODEL_PROPOSED_AND_RENDERED")
            self.assertEqual(result["human_story_quality"], "UNVERIFIED")
            self.assertFalse(result["best_updated"])

    def test_real_proposal_without_video_is_not_a_successful_fullcut(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._setup(root, rendered=False)
            result = assess_run(root)
            self.assertEqual(result["autonomous_candidate_status"], "MODEL_PROPOSED_BUT_NOT_RENDERED")

    def test_fixture_is_never_autonomous_even_if_rendered(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._setup(root, fixture=True)
            result = assess_run(root)
            self.assertEqual(result["autonomous_candidate_status"], "FIXTURE_ONLY")

    def test_missing_provenance_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            result = assess_run(Path(d))
            self.assertEqual(result["autonomous_candidate_status"], "UNVERIFIED")
            self.assertFalse(result["release_authorized"])

    def test_fake_model_mode_cannot_claim_autonomy(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._setup(root, real=False)
            result = assess_run(root)
            self.assertEqual(result["autonomous_candidate_status"], "NO_VERIFIED_REAL_PLANNER_PROPOSAL")

    def test_cli_is_read_only_to_run_and_writes_separate_report(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._setup(root)
            out = root / "separate_report.json"
            self.assertEqual(main(["--run-dir", str(root), "--out", str(out)]), 0)
            self.assertEqual(json.loads(out.read_text())["human_story_quality"], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
