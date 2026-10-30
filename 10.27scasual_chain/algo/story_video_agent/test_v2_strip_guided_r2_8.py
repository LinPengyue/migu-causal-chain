"""R2.8 visual gate unit tests (no API)."""
from __future__ import annotations

import unittest

import numpy as np

from story_video_agent.v2_strip_guided_r2_8_build_edl import build_r28_edl
from story_video_agent.v2_strip_guided_r2_8_visual_qc import (
    assert_negative_ranges_detected,
    classify_frame_features,
    frame_corruption_features,
)


class TestR28VisualFeatures(unittest.TestCase):
    def test_gray_still_blocked(self):
        im = np.full((180, 320, 3), 128.0, dtype=np.float32)
        feat = frame_corruption_features(im)
        kind, score, _ = classify_frame_features(feat)
        self.assertEqual(kind, "near_uniform_gray")
        self.assertGreaterEqual(score, 4.0)

    def test_synthetic_neon_macroblock_blocked(self):
        im = np.zeros((240, 426, 3), dtype=np.float32)
        im[:, :, 1] = 90  # dark-ish base
        # paint 16px neon magenta horizontal band + blocky edges
        im[60:76, :, 0] = 220
        im[60:76, :, 2] = 220
        im[60:76, :, 1] = 40
        for x in range(0, 426, 16):
            im[100:140, x : x + 8, 0] = 30
            im[100:140, x : x + 8, 1] = 210
            im[100:140, x : x + 8, 2] = 40
            im[100:140, x + 8 : x + 16, 0] = 200
            im[100:140, x + 8 : x + 16, 1] = 40
            im[100:140, x + 8 : x + 16, 2] = 200
        feat = frame_corruption_features(im)
        kind, score, detail = classify_frame_features(feat)
        self.assertIsNotNone(kind)
        self.assertGreaterEqual(score, 4.0)
        self.assertTrue(detail.get("reasons"))

    def test_cleanish_green_field_not_auto_blocked(self):
        im = np.zeros((240, 426, 3), dtype=np.float32)
        im[:, :, 1] = 140
        im[:, :, 0] = 40
        im[:, :, 2] = 40
        # mild noise
        rng = np.random.default_rng(0)
        im += rng.normal(0, 4, im.shape).astype(np.float32)
        im = np.clip(im, 0, 255)
        feat = frame_corruption_features(im)
        kind, score, _ = classify_frame_features(feat)
        self.assertIsNone(kind)
        self.assertLess(score, 4.0)

    def test_negative_range_helper(self):
        scan = {
            "n_anomalies": 2,
            "n_gray_anomalies": 0,
            "anomalies": [{"t": 58.4}, {"t": 86.1}],
        }
        out = assert_negative_ranges_detected(scan, [(58.0, 59.5), (85.5, 87.5)])
        self.assertTrue(out["all_negatives_detected"])
        miss = assert_negative_ranges_detected(scan, [(10.0, 11.0)])
        self.assertFalse(miss["all_negatives_detected"])


class TestR28Edl(unittest.TestCase):
    def test_g21_trimmed_and_g31_blocked(self):
        edl = build_r28_edl()
        self.assertFalse(edl["render_ready"])
        self.assertTrue(edl["gates"]["blocked_source_corruption"])
        by_id = {s["segment_id"]: s for s in edl["segments"]}
        self.assertEqual(by_id["edl_g21"]["media_in"], 3517.0)
        self.assertEqual(by_id["edl_g21"]["media_out"], 3533.0)
        self.assertLess(by_id["edl_g21"]["media_in"], by_id["edl_g21"]["shot_sec"])
        self.assertTrue(by_id["edl_g31"]["source_corruption_during_live_shot"])
        self.assertEqual(by_id["edl_g31"]["delivery_gate"], "BLOCKED_SOURCE_CORRUPTION")
        self.assertIn("edl_final_live_reaction", by_id)
        self.assertGreaterEqual(by_id["edl_final_live_reaction"]["media_in"], 7900.0)
        self.assertLess(by_id["edl_final_live_reaction"]["media_out"], 7950.0)
        self.assertEqual(edl["n_goal_segments"], 5)


if __name__ == "__main__":
    unittest.main()
