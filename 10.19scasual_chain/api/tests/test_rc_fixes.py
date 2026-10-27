"""RC 修复项：必填字段、sync rollback、callback 业务 code、stale timer。"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.adapters import AdapterConfig
from api.app import app
from api.callback import post_callback
from api.service import SERVICE
from api.task_manager import TASK_MANAGER


class _Capture:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.bodies: List[Dict[str, Any]] = []
        self.hits = 0
        self.mode = "ok"  # ok | code1 | fail_n
        self.fail_n = 0
        self.server: Optional[HTTPServer] = None

    def start(self, *, mode: str = "ok", fail_n: int = 0) -> str:
        self.mode = mode
        self.fail_n = fail_n
        self.hits = 0
        cap = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n)
                try:
                    body = json.loads(raw.decode("utf-8"))
                except Exception:
                    body = {}
                with cap.lock:
                    cap.hits += 1
                    hit = cap.hits
                    cap.bodies.append(body)
                    mode = cap.mode
                    fail_n = cap.fail_n
                if mode == "code1":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"code":"1","message":"biz fail"}')
                elif mode == "fail_n" and hit <= fail_n:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b"fail")
                elif mode == "code1_then_ok":
                    if hit <= fail_n:
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"code":"1","message":"biz fail"}')
                    else:
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"code":"0","message":"success"}')
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"code":"0","message":"success"}')

            def log_message(self, *a):  # noqa: A003
                return

        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_address[1]}/cb"

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()


@pytest.fixture(autouse=True)
def _reset():
    TASK_MANAGER.clear()
    SERVICE.callback_timeout_s = 1.0
    SERVICE.callback_max_attempts = 3
    SERVICE.callback_backoff_s = 0.02
    SERVICE.adapter_cfg = AdapterConfig(
        enable_deadline_timer=True,
        media_ms_per_wall_second=400_000.0,
        deadline_timer_min_wall_s=0.05,
        emit_highlight_type5=True,
    )
    yield
    TASK_MANAGER.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _full_clip(cid="c1", t=10.0, **over):
    d = {
        "clipId": cid,
        "videoPath": f"{cid}.mp4",
        "eventName": "进球",
        "eventTypeId": "goal",
        "eventTime": t,
        "score": None,
    }
    d.update(over)
    return d


def test_sync_requires_videoPath_eventName_eventTypeId(client: TestClient):
    base = {
        "taskId": "t",
        "matchId": "m",
        "clip": {
            "clipId": "c1",
            "eventTime": 1.0,
            "score": None,
        },
    }
    # missing videoPath/eventName/eventTypeId
    r = client.post("/highlight/sync", json=base)
    assert r.status_code == 422

    for field in ("videoPath", "eventName", "eventTypeId"):
        clip = _full_clip()
        del clip[field]
        r = client.post(
            "/highlight/sync",
            json={"taskId": "t", "matchId": "m", "clip": clip},
        )
        assert r.status_code == 422, field


def test_sync_rollback_allows_retry_same_clipId(client: TestClient):
    cap = _Capture()
    url = cap.start()
    try:
        assert (
            client.post(
                "/highlight/start",
                json={"taskId": "rb1", "matchId": "m", "callbackUrl": url},
            ).json()["code"]
            == "0"
        )
        clip = _full_clip("retry_me", 20.0)

        # 第一次 feed 抛错
        eng_cls = SERVICE._OnlineStripEngine
        calls = {"n": 0}
        real_feed = eng_cls.feed

        def boom(self, event):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated feed failure")
            return real_feed(self, event)

        with patch.object(eng_cls, "feed", boom):
            r1 = client.post(
                "/highlight/sync",
                json={"taskId": "rb1", "matchId": "m", "clip": clip},
            )
            assert r1.json()["code"] != "0"
            assert "algorithm error" in r1.json()["message"]

            task = TASK_MANAGER.get("rb1")
            assert task is not None
            assert "retry_me" not in task.received_clip_ids
            assert all(e.get("event_id") != "retry_me" for e in task.events)

            # 同一 clipId 必须能再次进入算法
            r2 = client.post(
                "/highlight/sync",
                json={"taskId": "rb1", "matchId": "m", "clip": clip},
            )
            assert r2.json()["code"] == "0"
            assert "retry_me" in task.received_clip_ids
            assert calls["n"] == 2
    finally:
        client.post("/highlight/end", json={"taskId": "rb1", "matchId": "m"})
        cap.stop()


def test_callback_http200_business_code1_retries():
    cap = _Capture()
    url = cap.start(mode="code1")
    try:
        rec = post_callback(
            url,
            {
                "taskId": "t",
                "matchId": "m",
                "highlightType": 1,
                "chainType": 1,
                "highlights": [],
            },
            timeout_s=1.0,
            max_attempts=3,
            backoff_s=0.01,
        )
        assert rec["ok"] is False
        assert rec["attempts"] == 3
        assert rec.get("callback_failed") is True
        assert cap.hits == 3
        assert "code=" in (rec.get("error") or "")
    finally:
        cap.stop()


def test_callback_http200_code1_then_ok():
    cap = _Capture()
    url = cap.start(mode="code1_then_ok", fail_n=2)
    try:
        rec = post_callback(
            url,
            {
                "taskId": "t",
                "matchId": "m",
                "highlightType": 1,
                "chainType": 1,
                "highlights": [{"clipId": "a", "start": 1.0, "end": 2.0}],
            },
            timeout_s=1.0,
            max_attempts=3,
            backoff_s=0.01,
        )
        assert rec["ok"] is True
        assert rec["attempts"] == 3
        assert cap.hits == 3
    finally:
        cap.stop()


def test_stale_deadline_timer_ignored(client: TestClient):
    cap = _Capture()
    url = cap.start()
    try:
        client.post(
            "/highlight/start",
            json={"taskId": "st1", "matchId": "m", "callbackUrl": url},
        )
        client.post(
            "/highlight/sync",
            json={
                "taskId": "st1",
                "matchId": "m",
                "clip": _full_clip("g1", 100.0, eventName="进球", eventTypeId="goal"),
            },
        )
        task = TASK_MANAGER.get("st1")
        assert task and task.scheduled_deadline_ms is not None
        old = int(task.scheduled_deadline_ms)
        # 模拟预约已被更新
        with task.lock:
            task.scheduled_deadline_ms = old + 999999
            n_before = len(task.emitted_result_ids)
        SERVICE._on_deadline_timer("st1", old)
        with task.lock:
            assert len(task.emitted_result_ids) == n_before
            # scheduled 未被 stale timer 改写回 old
            assert task.scheduled_deadline_ms == old + 999999
    finally:
        client.post("/highlight/end", json={"taskId": "st1", "matchId": "m"})
        cap.stop()
