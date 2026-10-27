"""协议层测试：媒体时间秒 + type=5/chainType=19 + 回归。"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from api.adapters import (
    AdapterConfig,
    CATEGORY_TO_HIGHLIGHT_TYPE,
    EXTERNAL_TIME_UNIT,
    MIGU_CHAIN_TYPE_MAP,
    MIGU_REEL_CHAIN_TYPE,
    TIME_MODE,
    build_highlight_time,
    category_to_highlight_type,
    event_time_to_ms,
    ms_to_media_seconds,
    template_to_chain_type,
)
from api.app import app
from api.service import SERVICE
from api.task_manager import TASK_MANAGER


class _CallbackCapture:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.bodies: List[Dict[str, Any]] = []
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self._fail_first_n = 0
        self._hits = 0
        self._always_fail = False

    def start(self, *, fail_first_n: int = 0, always_fail: bool = False) -> str:
        capture = self
        capture._fail_first_n = fail_first_n
        capture._always_fail = always_fail
        capture._hits = 0

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw.decode("utf-8"))
                except Exception:
                    body = {"_raw": raw.decode("utf-8", errors="replace")}
                with capture.lock:
                    capture._hits += 1
                    hit = capture._hits
                    capture.bodies.append(body)
                    fail = capture._always_fail or hit <= capture._fail_first_n
                if fail:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b"fail")
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"ok")

            def log_message(self, format, *args):  # noqa: A003
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_address[1]}/callback"

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()

    def wait_bodies(self, n: int, timeout: float = 60.0) -> List[Dict[str, Any]]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if len(self.bodies) >= n:
                    return list(self.bodies)
            time.sleep(0.05)
        with self.lock:
            return list(self.bodies)

    def wait_type(self, highlight_type: int, timeout: float = 60.0) -> Optional[Dict[str, Any]]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                for b in self.bodies:
                    if b.get("highlightType") == highlight_type:
                        return b
            time.sleep(0.05)
        with self.lock:
            for b in self.bodies:
                if b.get("highlightType") == highlight_type:
                    return b
        return None

    def hit_count(self) -> int:
        with self.lock:
            return self._hits


def _fast_timer_cfg(**kwargs) -> AdapterConfig:
    base = dict(
        reject_out_of_order=True,
        emit_highlight_type5=True,
        enable_deadline_timer=True,
        media_ms_per_wall_second=400_000.0,  # 60s media → ~0.15s wall
        deadline_timer_min_wall_s=0.05,
        deadline_timer_max_wall_s=5.0,
    )
    base.update(kwargs)
    return AdapterConfig(**base)


@pytest.fixture(autouse=True)
def _reset_state():
    TASK_MANAGER.clear()
    SERVICE.callback_timeout_s = 1.0
    SERVICE.callback_max_attempts = 3
    SERVICE.callback_backoff_s = 0.05
    SERVICE.adapter_cfg = _fast_timer_cfg()
    yield
    TASK_MANAGER.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _clip(clip_id: str, event_name: str, event_time_s: float, event_type_id: str | None = None):
    """eventTime 为媒体时间秒。"""
    return {
        "clipId": clip_id,
        "videoPath": f"{clip_id}.mp4",
        "eventName": event_name,
        "eventTypeId": event_type_id or event_name,
        "eventTime": event_time_s,
        "score": None,
    }


# ---------------------------------------------------------------------------
# 时间转换
# ---------------------------------------------------------------------------


def test_event_time_seconds_to_ms():
    assert event_time_to_ms(100.5) == 100500
    assert event_time_to_ms(108.351) == 108351
    assert event_time_to_ms("100.5") == 100500


def test_ms_to_media_seconds_and_build_highlight_time():
    assert TIME_MODE == "media_timeline"
    assert EXTERNAL_TIME_UNIT == "seconds"
    assert ms_to_media_seconds(100000) == 100.0
    assert ms_to_media_seconds(108000) == 108.0
    s, e = build_highlight_time(chain_t0_ms=100000, chain_t1_ms=108000)
    assert (s, e) == (100.0, 108.0)


# ---------------------------------------------------------------------------
# 18 + 19 mapping / highlightType
# ---------------------------------------------------------------------------

_EXPECTED_18 = {
    1: "corner_cross_goal",
    2: "rebound_follow_up_goal",
    3: "turnover_counter_goal",
    4: "penalty_scored_chain",
    5: "red_card_decision_chain",
    6: "goal_disallowed_chain",
    7: "var_penalty_cancelled_chain",
    8: "var_overturn_chain",
    9: "shot_save_chain",
    10: "shot_post_bar_chain",
    11: "second_phase_after_frame_chain",
    12: "goal_line_extreme_save_chain",
    13: "throw_in_build_up_chain",
    14: "own_goal_causal_chain",
    15: "keeper_spill_danger_chain",
    16: "deflection_goal_chain",
    17: "quick_restart_set_piece_chain",
    18: "outcome_other",
}


@pytest.mark.parametrize("chain_type,tid", list(_EXPECTED_18.items()))
def test_migu_chain_type_mapping_18(chain_type: int, tid: str):
    assert MIGU_CHAIN_TYPE_MAP[tid] == chain_type
    assert template_to_chain_type(tid) == chain_type


@pytest.mark.parametrize(
    "tid",
    ["individual_breakthrough_goal", "team_buildup_goal", "corner_coop_goal"],
)
def test_extra_outcome_still_map_to_18_not_19(tid: str):
    assert template_to_chain_type(tid) == 18
    assert tid not in (None,)
    assert MIGU_REEL_CHAIN_TYPE == 19


@pytest.mark.parametrize(
    "cat,ht",
    [("outcome", 1), ("correction", 2), ("danger", 3), ("special", 4)],
)
def test_highlight_type_by_category(cat: str, ht: int):
    assert category_to_highlight_type(cat) == ht
    assert CATEGORY_TO_HIGHLIGHT_TYPE[cat] == ht


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _start_sync(client, task_id, match_id, url, clips):
    assert (
        client.post(
            "/highlight/start",
            json={"taskId": task_id, "matchId": match_id, "callbackUrl": url},
        ).json()["code"]
        == "0"
    )
    for c in clips:
        rr = client.post(
            "/highlight/sync",
            json={"taskId": task_id, "matchId": match_id, "clip": c},
        )
        assert rr.json()["code"] == "0", rr.text


def _assert_biz(body, allowed):
    ids = [h["clipId"] for h in body.get("highlights") or []]
    assert ids
    assert all(cid in allowed for cid in ids)
    assert all(not str(cid).startswith("clip") for cid in ids)


# ---------------------------------------------------------------------------
# 在线 + 赛后
# ---------------------------------------------------------------------------


def test_online_corner_and_post_match_type5(client: TestClient):
    cap = _CallbackCapture()
    url = cap.start()
    try:
        _start_sync(
            client,
            "t5",
            "m5",
            url,
            [
                _clip("biz_corner", "角球", 100.0, "corner"),
                _clip("biz_cross", "传中", 103.0, "cross"),
                _clip("biz_header", "头球", 106.0, "header_shot"),
                _clip("biz_goal", "进球", 108.0, "goal"),
            ],
        )
        online = cap.wait_type(1, timeout=10)
        assert online is not None
        print("CORNER_CALLBACK_JSON=", json.dumps(online, ensure_ascii=False))
        assert online["highlightType"] == 1
        assert online["chainType"] == 1
        _assert_biz(online, {"biz_corner", "biz_cross", "biz_header", "biz_goal"})
        for h in online["highlights"]:
            assert h["start"] == 100.0
            assert h["end"] == 108.0

        assert (
            client.post("/highlight/end", json={"taskId": "t5", "matchId": "m5"}).json()["code"]
            == "0"
        )
        # end 同步 callback：从已收包或再等
        post = None
        for _ in range(50):
            with cap.lock:
                for b in cap.bodies:
                    if b.get("highlightType") == 5:
                        post = b
                        break
            if post:
                break
            time.sleep(0.05)
        assert post is not None, cap.bodies
        print("TYPE5_CALLBACK_JSON=", json.dumps(post, ensure_ascii=False))
        assert post["highlightType"] == 5
        assert post["chainType"] == 19
        assert post["taskId"] == "t5"
        _assert_biz(post, {"biz_corner", "biz_cross", "biz_header", "biz_goal"})
        # 真实 reel：generated_results 非空
        task = TASK_MANAGER.get("t5")
        assert task and task.status == "finished"
        assert task.generated_results
        # end 幂等
        assert (
            client.post("/highlight/end", json={"taskId": "t5", "matchId": "m5"}).json()["code"]
            == "0"
        )
    finally:
        cap.stop()


def test_deadline_without_dummy_sync(client: TestClient):
    cap = _CallbackCapture()
    url = cap.start()
    try:
        _start_sync(
            client,
            "dl1",
            "m",
            url,
            [
                _clip("biz_corner", "角球", 100.0, "corner"),
                _clip("biz_cross", "传中", 103.0, "cross"),
                _clip("biz_header", "头球", 106.0, "header_shot"),
                _clip("biz_goal", "进球", 108.0, "goal"),
            ],
        )
        body = cap.wait_type(1, timeout=10)
        assert body and body["chainType"] == 1
        assert body["highlights"][0]["start"] == 100.0
    finally:
        client.post("/highlight/end", json={"taskId": "dl1", "matchId": "m"})
        cap.stop()


def test_case_b_penalty(client: TestClient):
    cap = _CallbackCapture()
    url = cap.start()
    try:
        _start_sync(
            client,
            "cb",
            "mb",
            url,
            [
                _clip("b_pen", "点球", 100.0, "penalty"),
                _clip("b_goal", "进球", 105.0, "goal"),
            ],
        )
        body = cap.wait_type(1, timeout=10)
        assert body
        assert body["highlightType"] == 1 and body["chainType"] == 4
        assert body["highlights"][0]["start"] == 100.0
        assert body["highlights"][0]["end"] == 105.0
    finally:
        client.post("/highlight/end", json={"taskId": "cb", "matchId": "mb"})
        cap.stop()


def test_case_c_correction(client: TestClient):
    cap = _CallbackCapture()
    url = cap.start()
    try:
        _start_sync(
            client,
            "cc",
            "mc",
            url,
            [
                _clip("c_goal", "进球", 100.0, "goal"),
                _clip("c_var", "VAR", 108.0, "var"),
                _clip("c_cont", "裁判判罚", 112.0, "controversy"),
            ],
        )
        body = cap.wait_type(2, timeout=10)
        assert body
        assert body["highlightType"] == 2 and body["chainType"] == 6
    finally:
        client.post("/highlight/end", json={"taskId": "cc", "matchId": "mc"})
        cap.stop()


def test_sync_missing_task(client: TestClient):
    r = client.post(
        "/highlight/sync",
        json={"taskId": "nope", "matchId": "m", "clip": _clip("c1", "进球", 1.0)},
    )
    assert r.json()["code"] != "0"


def test_out_of_order_rejected(client: TestClient):
    cap = _CallbackCapture()
    url = cap.start()
    try:
        client.post(
            "/highlight/start",
            json={"taskId": "oo1", "matchId": "m", "callbackUrl": url},
        )
        client.post(
            "/highlight/sync",
            json={"taskId": "oo1", "matchId": "m", "clip": _clip("c2", "进球", 50.0)},
        )
        r = client.post(
            "/highlight/sync",
            json={"taskId": "oo1", "matchId": "m", "clip": _clip("c1", "射门", 10.0)},
        )
        assert r.json()["code"] != "0"
        assert "out-of-order" in r.json()["message"]
    finally:
        client.post("/highlight/end", json={"taskId": "oo1", "matchId": "m"})
        cap.stop()


def test_multi_task_isolation(client: TestClient):
    cap_a = _CallbackCapture()
    cap_b = _CallbackCapture()
    url_a = cap_a.start()
    url_b = cap_b.start()
    try:
        _start_sync(
            client,
            "taskA",
            "matchA",
            url_a,
            [
                _clip("a_c", "角球", 100.0, "corner"),
                _clip("a_x", "传中", 103.0, "cross"),
                _clip("a_h", "头球", 106.0, "header_shot"),
                _clip("a_g", "进球", 108.0, "goal"),
            ],
        )
        _start_sync(
            client,
            "taskB",
            "matchB",
            url_b,
            [
                _clip("b_p", "点球", 200.0, "penalty"),
                _clip("b_g", "进球", 205.0, "goal"),
            ],
        )
        ba = cap_a.wait_type(1, timeout=10)
        bb = cap_b.wait_type(1, timeout=10)
        assert ba and bb
        assert ba["taskId"] == "taskA" and bb["taskId"] == "taskB"
        assert ba["chainType"] == 1 and bb["chainType"] == 4
        client.post("/highlight/end", json={"taskId": "taskA", "matchId": "matchA"})
        assert TASK_MANAGER.get("taskB").status == "running"
    finally:
        client.post("/highlight/end", json={"taskId": "taskB", "matchId": "matchB"})
        cap_a.stop()
        cap_b.stop()


def test_callback_retries_then_success(client: TestClient):
    cap = _CallbackCapture()
    url = cap.start(fail_first_n=2)
    try:
        SERVICE.callback_max_attempts = 3
        SERVICE.callback_backoff_s = 0.01
        _start_sync(
            client,
            "rt1",
            "m",
            url,
            [
                _clip("c1", "角球", 100.0, "corner"),
                _clip("c2", "传中", 103.0, "cross"),
                _clip("c3", "头球", 106.0, "header_shot"),
                _clip("c4", "进球", 108.0, "goal"),
            ],
        )
        assert cap.wait_type(1, timeout=15)
        deadline = time.time() + 5
        while time.time() < deadline and cap.hit_count() < 3:
            time.sleep(0.05)
        assert cap.hit_count() >= 3
        t = TASK_MANAGER.get("rt1")
        assert t and any(r.get("ok") and r.get("attempts") == 3 for r in t.callback_records)
    finally:
        client.post("/highlight/end", json={"taskId": "rt1", "matchId": "m"})
        cap.stop()


def test_no_match_clock_symbols_in_adapters():
    import api.adapters as ad

    assert not hasattr(ad.AdapterConfig, "match_ms_per_wall_second")
    assert hasattr(ad.DEFAULT_ADAPTER_CONFIG, "media_ms_per_wall_second")
    assert "match_ms" not in open(ad.__file__, encoding="utf-8").read()


def test_debug_route_hidden_by_default(client: TestClient):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/debug/task/{task_id}" not in paths
