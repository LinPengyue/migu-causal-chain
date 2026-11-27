"""Phase 2C 负例与可信反馈单测。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_video_agent.api_provider import (
    ApiCallError,
    ApiConfigError,
    ApiProvider,
    EndpointConfig,
    api_enabled,
    smoke_enabled,
)
from story_video_agent.memory import Memory
from story_video_agent.runner import _derive_terminal_status, solve
from story_video_agent.state import FRANCE_PERCEPTION_FOCUS, validate_plan_payload
from story_video_agent.test_perception import _france_like_story, _make_test_video
from story_video_agent.vision_provider import (
    EvidenceNormalizationError,
    VisionProvider,
    normalize_evidence,
)


class Phase2CNegativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="sva2c_")
        cls.video = _make_test_video(Path(cls._tmpdir.name) / "toy.mp4", duration=40.0)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def test_missing_key_fails_in_require_real(self) -> None:
        cfg = {
            "planner": EndpointConfig("planner", "", "", ""),
            "vision": EndpointConfig("vision", "", "", ""),
        }
        with self.assertRaises(ApiConfigError):
            ApiProvider(force_mock=False, require_real=True, configs=cfg)

    def test_api_failure_not_observed(self) -> None:
        api = ApiProvider(force_mock=True)
        vision = VisionProvider(api, force_mock=True)

        def boom(**kwargs):
            return {
                "content": "",
                "provider_mode": "degraded",
                "provider": "degraded",
                "error": "HTTP 500",
                "usage": {},
                "model": "x",
            }

        with mock.patch.object(api, "vision_json", side_effect=boom):
            out = vision.describe_frames(
                gap_id="verify_equalizer_goal_action",
                gap_note="t",
                frame_paths=[],
                frame_ids=["f1"],
                frame_bindings=[{"frame_id": "f1", "requested_media_sec": 1.0}],
            )
        self.assertEqual(out["provider_mode"], "degraded")
        self.assertFalse(out.get("normalized_ok"))
        self.assertEqual(out.get("frame_ids"), [])

    def test_illegal_json_not_observed(self) -> None:
        with self.assertRaises(EvidenceNormalizationError):
            normalize_evidence(
                {},  # type: ignore[arg-type]
                gap_id="g",
                frame_ids=["f1"],
                frame_bindings=[],
                provider_mode="real",
            )
        api = ApiProvider(force_mock=True)
        vision = VisionProvider(api, force_mock=True)
        with mock.patch.object(
            api,
            "vision_json",
            return_value={
                "content": "not-json at all",
                "provider_mode": "real",
                "provider": "openai_compatible",
                "model": "m",
                "usage": {},
            },
        ):
            out = vision.describe_frames(
                gap_id="g",
                gap_note="",
                frame_paths=[],
                frame_ids=["f1"],
                frame_bindings=[{"frame_id": "f1"}],
            )
        self.assertFalse(out.get("normalized_ok"))
        self.assertIn("EvidenceNormalizationError", out.get("error", ""))

    def test_invalid_frame_id_rejected(self) -> None:
        with self.assertRaises(EvidenceNormalizationError):
            normalize_evidence(
                {
                    "observed_actions": ["x"],
                    "story_relation": "y",
                    "confidence": 0.5,
                    "frame_ids": ["not_in_input"],
                },
                gap_id="g",
                frame_ids=["f1", "f2"],
                frame_bindings=[{"frame_id": "f1"}, {"frame_id": "f2"}],
                provider_mode="mock",
            )

    def test_empty_evidence_rejected(self) -> None:
        with self.assertRaises(EvidenceNormalizationError):
            normalize_evidence(
                {
                    "observed_actions": [],
                    "story_relation": "",
                    "confidence": 0.9,
                    "frame_ids": ["f1"],
                },
                gap_id="g",
                frame_ids=["f1"],
                frame_bindings=[{"frame_id": "f1"}],
                provider_mode="real",
            )

    def test_no_auto_all_frames(self) -> None:
        # 模型只引用 f1，不得偷偷塞入 f2
        ev = normalize_evidence(
            {
                "observed_actions": ["shot"],
                "story_relation": "goal-ish",
                "confidence": 0.4,
                "frame_ids": ["f1"],
            },
            gap_id="verify_equalizer_goal_action",
            frame_ids=["f1", "f2"],
            frame_bindings=[
                {"frame_id": "f1", "requested_media_sec": 1.0},
                {"frame_id": "f2", "requested_media_sec": 2.0},
            ],
            provider_mode="mock",
        )
        self.assertEqual(ev["frame_ids"], ["f1"])
        self.assertEqual(len(ev["frame_time_bindings"]), 1)

    def test_vlm_score_conflict(self) -> None:
        api = ApiProvider(force_mock=True)
        vision = VisionProvider(api, force_mock=True)
        with mock.patch.object(
            api,
            "vision_json",
            return_value={
                "content": json.dumps(
                    {
                        "observed_actions": ["unrelated crowd shot"],
                        "story_relation": "no goal visible",
                        "confidence": 0.1,
                        "frame_ids": ["f1"],
                        "notes": "irrelevant",
                    }
                ),
                "provider_mode": "mock",
                "provider": "mock",
                "model": "mock",
                "usage": {},
            },
        ):
            out = vision.describe_frames(
                gap_id="verify_equalizer_goal_action",
                gap_note="equalizer",
                frame_paths=[],
                frame_ids=["f1"],
                frame_bindings=[{"frame_id": "f1"}],
                gap={"kind": "action_verify"},
            )
        self.assertFalse(out.get("normalized_ok"))
        self.assertIn("conflict", out)

    def test_memory_rejects_unnormalized_observed(self) -> None:
        mem = Memory()
        with self.assertRaises(ValueError):
            mem.mark_observed("g", {"normalized_ok": False})

    def test_terminal_status_not_blind_observed(self) -> None:
        tasks = [
            {"status": "unresolved", "gap_id": "a"},
            {"status": "sampled", "gap_id": "b"},
        ]
        self.assertEqual(
            _derive_terminal_status(
                perception=True, media_only=False, dry_run=False, tasks=tasks
            ),
            "unresolved",
        )
        tasks2 = [
            {
                "status": "observed",
                "gap_id": "a",
                "visual_evidence": {"normalized_ok": True, "frame_ids": ["f1"]},
            }
        ]
        self.assertEqual(
            _derive_terminal_status(
                perception=True, media_only=False, dry_run=False, tasks=tasks2
            ),
            "observed",
        )

    def test_budget_exhaustion_status(self) -> None:
        story = _france_like_story()
        result = solve(
            story,
            video_path=str(self.video),
            dry_run=False,
            perception=True,
            force_mock_vlm=True,
            focus_gap_ids=list(FRANCE_PERCEPTION_FOCUS),
            max_steps=30,
            frame_budget=1,
            frame_dir=str(Path(self._tmpdir.name) / "budget"),
        )
        self.assertIn(
            result["status"],
            ("frame_budget_exhausted", "partial_observed", "unresolved"),
        )
        self.assertFalse(result["verification_complete"])
        for task in result["evidence_tasks"]:
            if task["status"] == "observed":
                self.assertTrue(task["visual_evidence"].get("normalized_ok"))

    def test_mock_france_loop_still_works(self) -> None:
        story = _france_like_story()
        result = solve(
            story,
            video_path=str(self.video),
            dry_run=False,
            perception=True,
            force_mock_vlm=True,
            use_llm_planner=True,
            focus_gap_ids=list(FRANCE_PERCEPTION_FOCUS),
            max_steps=24,
            frame_budget=12,
            frame_dir=str(Path(self._tmpdir.name) / "ok"),
        )
        self.assertTrue(result["structure_ok"], result.get("structure_problems"))
        self.assertEqual(result["status"], "observed")
        self.assertEqual(len(result["evidence_tasks"]), 3)
        for task in result["evidence_tasks"]:
            self.assertEqual(task["status"], "observed")
            ev = task["visual_evidence"]
            self.assertEqual(ev["provider_mode"], "mock")
            self.assertTrue(ev["normalized_ok"])
            self.assertTrue(ev["frame_ids"])
        facts = result["memory"]["gap_stages"]
        self.assertTrue(all(v == "observed" for v in facts.values()))
        self.assertTrue(result["memory"].get("checked_intervals"))

    def test_retryable_classification(self) -> None:
        err = ApiCallError("HTTP 429", retryable=True, http_status=429)
        self.assertTrue(err.retryable)
        err2 = ApiCallError("HTTP 401", retryable=False, http_status=401)
        self.assertFalse(err2.retryable)

    def test_smoke_gate_default_off(self) -> None:
        self.assertFalse(smoke_enabled() and not os.environ.get("STORY_API_SMOKE"))


if __name__ == "__main__":
    unittest.main()
