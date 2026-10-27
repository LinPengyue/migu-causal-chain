"""URLError 脱敏分类与无计费网络诊断辅助测试（禁止 /chat/completions）。"""

from __future__ import annotations

import json
import os
import socket
import ssl
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from story_video_agent.api_provider import (
    ApiProvider,
    EndpointConfig,
    _classify_error,
    _network_error_category,
    _sanitize_error_text,
    failure_status_from_exc,
)
from story_video_agent.frames import FrameStore


class SanitizeClassifyTests(unittest.TestCase):
    def test_sanitize_strips_key_bearer_base64_proxy_creds(self) -> None:
        raw = (
            "Authorization: Bearer sk-SECRETKEY1234567890 "
            "proxy=http://user:hunter2@127.0.0.1:8080 "
            "data:image/jpeg;base64,AAAAIIIIIIIIIIII"
        )
        out = _sanitize_error_text(raw)
        self.assertNotIn("sk-SECRET", out)
        self.assertNotIn("hunter2", out)
        self.assertNotIn("AAAAIIII", out)
        self.assertIn("[REDACTED]", out)
        self.assertIn("[REDACTED_USER]:[REDACTED_PASS]", out)
        self.assertIn("data:image/<redacted_base64>", out)

    def test_urlerror_dns_gaierror(self) -> None:
        reason = socket.gaierror(-3, "Temporary failure in name resolution")
        exc = urllib.error.URLError(reason)
        retryable, status, msg = _classify_error(exc)
        self.assertTrue(retryable)
        self.assertEqual(status, 0)
        self.assertIn("category=dns", msg)
        self.assertIn("reason_type=gaierror", msg)
        self.assertIn("name resolution", msg.lower())
        self.assertEqual(failure_status_from_exc(exc), "network_dns")

    def test_urlerror_proxy_tunnel_403(self) -> None:
        reason = OSError("Tunnel connection failed: 403 Forbidden")
        exc = urllib.error.URLError(reason)
        _, _, msg = _classify_error(exc)
        self.assertIn("category=proxy", msg)
        self.assertIn("reason_type=OSError", msg)
        self.assertEqual(failure_status_from_exc(exc), "network_proxy")
        self.assertEqual(_network_error_category(reason), "proxy")

    def test_urlerror_timeout(self) -> None:
        exc = urllib.error.URLError(TimeoutError("The read operation timed out"))
        _, _, msg = _classify_error(exc)
        self.assertIn("category=timeout", msg)
        self.assertEqual(failure_status_from_exc(exc), "network_timeout")

    def test_urlerror_tls_keyword(self) -> None:
        reason = ssl.SSLError("CERTIFICATE_VERIFY_FAILED")
        exc = urllib.error.URLError(reason)
        _, _, msg = _classify_error(exc)
        self.assertIn("category=tls", msg)
        self.assertEqual(failure_status_from_exc(exc), "network_tls")

    def test_legacy_bare_urlerror_type_name_not_enough(self) -> None:
        """Regression: must not collapse to bare 'URLError' without category."""
        exc = urllib.error.URLError(socket.gaierror(-2, "Name or service not known"))
        _, _, msg = _classify_error(exc)
        self.assertNotEqual(msg, "URLError")
        self.assertTrue(msg.startswith("URLError category="))


class InjectedUrlErrorProviderTests(unittest.TestCase):
    def test_chat_records_sanitized_dns_category(self) -> None:
        configs = {
            "planner": EndpointConfig(
                role="planner",
                base_url="https://example.test/v1",
                api_key="sk-testkey-should-redact-XXXX",
                model="m",
                max_retries=0,
            ),
            "vision": EndpointConfig(
                role="vision",
                base_url="https://example.test/v1",
                api_key="sk-testkey-should-redact-XXXX",
                model="m",
                max_retries=0,
            ),
        }
        with mock.patch.dict(os.environ, {"STORY_API_MAX_CALLS": "3"}, clear=False):
            api = ApiProvider(
                force_mock=False,
                require_real=True,
                configs=configs,
                max_calls=3,
                required_roles=["vision"],
            )

            def boom(*_a, **_k):
                raise urllib.error.URLError(
                    socket.gaierror(-3, "Temporary failure in name resolution")
                )

            with mock.patch.object(api, "_post_chat", side_effect=boom):
                with self.assertRaises(Exception):
                    api.chat(
                        role="vision",
                        messages=[{"role": "user", "content": "x"}],
                        cache_key="diag1",
                        allow_degraded_fallback=False,
                    )
        rec = api.stats.calls[-1]
        self.assertFalse(rec.ok)
        self.assertIn("category=dns", rec.error)
        self.assertEqual(rec.failure_status, "network_dns")
        blob = json.dumps(rec.to_dict())
        self.assertNotIn("sk-testkey", blob)
        summary_blob = json.dumps(api.stats.summary())
        self.assertNotIn("sk-testkey", summary_blob)


class SampleTimesCenterTests(unittest.TestCase):
    def test_three_frames_include_equalizer_center(self) -> None:
        # sample_times 不依赖 store 状态；不改全局算法，仅验证 count=3 含中心
        times2 = FrameStore.sample_times(None, 3059.903, 3071.903, count=2)  # type: ignore[arg-type]
        times3 = FrameStore.sample_times(None, 3059.903, 3071.903, count=3)  # type: ignore[arg-type]
        self.assertEqual(times2, [3059.953, 3071.853])
        self.assertEqual(times3, [3059.953, 3065.903, 3071.853])
        self.assertAlmostEqual(times3[1], 3065.903, places=3)


if __name__ == "__main__":
    unittest.main()
