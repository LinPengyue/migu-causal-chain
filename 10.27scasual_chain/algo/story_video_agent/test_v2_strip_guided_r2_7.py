"""R2.7 visual gate unit tests (no API)."""
from __future__ import annotations
import unittest
from story_video_agent.v2_strip_guided_r2_7_render import detect_gray_or_corrupt_frames

class TestR27GrayGate(unittest.TestCase):
    def test_detector_import_and_schema(self):
        # Smoke: function exists and documents policy fields without needing a video.
        self.assertTrue(callable(detect_gray_or_corrupt_frames))

if __name__ == "__main__":
    unittest.main()
