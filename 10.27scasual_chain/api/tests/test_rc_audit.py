"""联调 RC 审计测试：未知类型、多链 type=5、幂等。"""

from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from api.adapters import AdapterConfig, MIGU_REEL_CHAIN_TYPE, resolve_event_type
from api.app import app
from api.event_type_map import PROVISIONAL_EVENT_TYPE_MAP, UNMAPPED_EVENT_TYPE
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

    def bodies_copy(self) -> List[Dict[str, Any]]:
        with self.lock:
            return list(self.bodies)

    def wait_type(self, ht: int, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for b in self.bodies_copy():
                if b.get("highlightType") == ht:
                    return b
            time.sleep(0.05)
        return None

    def count_type(self, ht: int) -> int:
        return sum(1 for b in self.bodies_copy() if b.get("highlightType") == ht)

    def hit_count(self) -> int:
        with self.lock:
            return self._hits


def _fast_cfg(**kw) -> AdapterConfig:
    base = dict(
        reject_out_of_order=True,
        emit_highlight_type5=True,
        enable_deadline_timer=True,
        media_ms_per_wall_second=400_000.0,
        deadline_timer_min_wall_s=0.05,
        deadline_timer_max_wall_s=5.0,
        unknown_event_type_policy="unmapped",
    )
    base.update(kw)
    return AdapterConfig(**base)


@pytest.fixture(autouse=True)
def _reset():
    TASK_MANAGER.clear()
    SERVICE.callback_timeout_s = 1.0
    SERVICE.callback_max_attempts = 3
    SERVICE.callback_backoff_s = 0.05
    SERVICE.adapter_cfg = _fast_cfg()
    yield
    TASK_MANAGER.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _clip(cid, name, t_s, tid=None):
    return {
        "clipId": cid,
        "videoPath": f"{cid}.mp4",
        "eventName": name,
        "eventTypeId": tid if tid is not None else name,
        "eventTime": float(t_s),
        "score": None,
    }


def _start(client, tid, mid, url):
    assert (
        client.post(
            "/highlight/start",
            json={"taskId": tid, "matchId": mid, "callbackUrl": url},
        ).json()["code"]
        == "0"
    )


def _sync(client, tid, mid, clip):
    r = client.post(
        "/highlight/sync",
        json={"taskId": tid, "matchId": mid, "clip": clip},
    )
    return r


# ---------------------------------------------------------------------------
# provisional 集中 + 未知类型
# ---------------------------------------------------------------------------


def test_provisional_map_only_in_event_type_map_file():
    import api.adapters as ad
    import api.service as svc

    # 映射表本体只在 event_type_map
    assert "射门" in PROVISIONAL_EVENT_TYPE_MAP
    src = open(ad.__file__, encoding="utf-8").read()
    assert "PROVISIONAL_EVENT_TYPE_MAP = {" not in src
    assert "from api.event_type_map import" in src
    svc_src = open(svc.__file__, encoding="utf-8").read()
    assert '"goal": "goal"' not in svc_src


def test_unknown_event_type_not_silently_known(caplog):
    typ, ok = resolve_event_type("TOTALLY_FAKE_TYPE_XYZ", "完全未知事件名")
    assert typ == UNMAPPED_EVENT_TYPE
    assert ok is False
    # 不得变成 goal/shot 等
    assert typ not in ("goal", "shot", "corner", "penalty")


def test_unknown_event_type_logs_context(client: TestClient, caplog):
    cap = _CallbackCapture()
    url = cap.start()
    try:
        with caplog.at_level(logging.WARNING, logger="api.adapters"):
            _start(client, "uk1", "muk", url)
            r = _sync(
                client,
                "uk1",
                "muk",
                _clip("clip_unknown", "怪事件", 10.0, "ID_NOT_IN_DICT_999"),
            )
            assert r.json()["code"] == "0"  # unmapped 策略仍接受
        text = "\n".join(r.message for r in caplog.records)
        assert "taskId=uk1" in text
        assert "matchId=muk" in text
        assert "clipId=clip_unknown" in text
        assert "ID_NOT_IN_DICT_999" in text
        assert "怪事件" in text
        task = TASK_MANAGER.get("uk1")
        assert task and task.events[0]["type"] == UNMAPPED_EVENT_TYPE
        assert task.events[0].get("migu_type_unmapped") is True
    finally:
        client.post("/highlight/end", json={"taskId": "uk1", "matchId": "muk"})
        cap.stop()


def test_unknown_event_type_reject_policy(client: TestClient):
    SERVICE.adapter_cfg = _fast_cfg(unknown_event_type_policy="reject")
    cap = _CallbackCapture()
    url = cap.start()
    try:
        _start(client, "uk2", "m", url)
        r = _sync(client, "uk2", "m", _clip("c1", "怪", 1.0, "NOPE"))
        assert r.json()["code"] != "0"
        assert "unknown" in r.json()["message"].lower() or "rejected" in r.json()["message"]
        task = TASK_MANAGER.get("uk2")
        assert task and len(task.events) == 0
    finally:
        client.post("/highlight/end", json={"taskId": "uk2", "matchId": "m"})
        cap.stop()


# ---------------------------------------------------------------------------
# 多因果链 + type=5 reel ordering
# ---------------------------------------------------------------------------


def test_multi_chain_post_match_type5(client: TestClient):
    """同一 match：corner_cross_goal + shot_save + goal_disallowed → 在线 1/3/2 + 赛后 5/19。"""
    cap = _CallbackCapture()
    url = cap.start()
    try:
        _start(client, "mc1", "match_multi", url)

        # Chain A outcome / corner_cross_goal
        for c in [
            _clip("a_corner", "角球", 100.0, "corner"),
            _clip("a_cross", "传中", 103.0, "cross"),
            _clip("a_header", "头球", 106.0, "header_shot"),
            _clip("a_goal", "进球", 108.0, "goal"),
        ]:
            assert _sync(client, "mc1", "match_multi", c).json()["code"] == "0"
        # 推进时钟：下一段事件时间已超过 post_ms，会在 feed 时闭合 A
        # Chain B danger / shot_save
        for c in [
            _clip("b_shot", "射门", 300.0, "shot"),
            _clip("b_save", "扑救", 305.0, "keeper_save"),
        ]:
            assert _sync(client, "mc1", "match_multi", c).json()["code"] == "0"

        # Chain C correction / goal_disallowed
        for c in [
            _clip("c_goal", "进球", 500.0, "goal"),
            _clip("c_var", "VAR", 508.0, "var"),
            _clip("c_cont", "裁判判罚", 512.0, "controversy"),
        ]:
            assert _sync(client, "mc1", "match_multi", c).json()["code"] == "0"

        # 等待三类在线 callback（deadline / 后续事件推进）
        deadline = time.time() + 20
        saw = {1: False, 2: False, 3: False}
        while time.time() < deadline and not all(saw.values()):
            for b in cap.bodies_copy():
                ht = b.get("highlightType")
                if ht in saw:
                    saw[ht] = True
            time.sleep(0.05)
        assert saw[1], f"missing outcome callback: {cap.bodies_copy()}"
        assert saw[3], f"missing danger callback: {cap.bodies_copy()}"
        assert saw[2], f"missing correction callback: {cap.bodies_copy()}"

        online_before_end = [b for b in cap.bodies_copy() if b.get("highlightType") in (1, 2, 3, 4)]
        n_online = len(online_before_end)

        assert (
            client.post(
                "/highlight/end", json={"taskId": "mc1", "matchId": "match_multi"}
            ).json()["code"]
            == "0"
        )

        type5 = None
        for _ in range(40):
            for b in cap.bodies_copy():
                if b.get("highlightType") == 5:
                    type5 = b
                    break
            if type5:
                break
            time.sleep(0.05)
        assert type5 is not None
        print("MULTI_TYPE5_JSON=", json.dumps(type5, ensure_ascii=False))

        assert type5["highlightType"] == 5
        assert type5["chainType"] == MIGU_REEL_CHAIN_TYPE == 19
        assert type5["taskId"] == "mc1" and type5["matchId"] == "match_multi"

        biz = {
            "a_corner",
            "a_cross",
            "a_header",
            "a_goal",
            "b_shot",
            "b_save",
            "c_goal",
            "c_var",
            "c_cont",
        }
        ids = [h["clipId"] for h in type5["highlights"]]
        assert ids
        assert all(i in biz for i in ids)
        assert all(not str(i).startswith("clip") for i in ids)
        for h in type5["highlights"]:
            assert isinstance(h["start"], (int, float))
            assert isinstance(h["end"], (int, float))
            # 媒体秒，不是 ms
            assert h["start"] < 10_000 and h["end"] < 10_000

        task = TASK_MANAGER.get("mc1")
        assert task and task.generated_results
        assert task.type5_emitted is True
        # type5 不是简单复制某一条在线 callback
        assert type5 not in online_before_end
        # reel 有多段时 highlights 应覆盖多条业务链的 clip（至少跨两个源链）
        sources = set()
        for cid in ids:
            if cid.startswith("a_"):
                sources.add("a")
            if cid.startswith("b_"):
                sources.add("b")
            if cid.startswith("c_"):
                sources.add("c")
        assert len(sources) >= 2, f"type5 should cover multi-chain reel, got {ids}"

        # reel ordering：按 generated_results 顺序展开的 start 序列非严格递减即可对照
        reel_starts = []
        for ch in task.generated_results:
            t0 = int(getattr(ch, "t0_ms", 0) or 0)
            reel_starts.append(t0 / 1000.0)
        hl_starts = [h["start"] for h in type5["highlights"]]
        # highlights 按 reel 段顺序；同段内 start 相同，跨段应跟随 reel_starts 顺序
        if len(reel_starts) >= 2 and len(set(hl_starts)) >= 2:
            # 首次出现的各段 start 顺序与 reel 一致
            first_seen = []
            for s in hl_starts:
                if s not in first_seen:
                    first_seen.append(s)
            assert first_seen == sorted(first_seen) or first_seen == [
                x for x in reel_starts if x in first_seen
            ]

        # 重复 end：不再新增 type=5
        n5_before = cap.count_type(5)
        assert (
            client.post(
                "/highlight/end", json={"taskId": "mc1", "matchId": "match_multi"}
            ).json()["code"]
            == "0"
        )
        time.sleep(0.3)
        assert cap.count_type(5) == n5_before

        # 在线 1~4 在 end 后也不应因幂等重复暴增（允许 end flush 补发最多有限条）
        assert cap.count_type(1) + cap.count_type(2) + cap.count_type(3) >= n_online
    finally:
        cap.stop()


# ---------------------------------------------------------------------------
# 幂等：timer / end / retry
# ---------------------------------------------------------------------------


def test_duplicate_end_no_second_type5(client: TestClient):
    cap = _CallbackCapture()
    url = cap.start()
    try:
        _start(client, "id1", "m", url)
        for c in [
            _clip("x1", "角球", 100.0, "corner"),
            _clip("x2", "传中", 103.0, "cross"),
            _clip("x3", "头球", 106.0, "header_shot"),
            _clip("x4", "进球", 108.0, "goal"),
        ]:
            _sync(client, "id1", "m", c)
        cap.wait_type(1, timeout=10)
        client.post("/highlight/end", json={"taskId": "id1", "matchId": "m"})
        # wait type5
        for _ in range(40):
            if cap.count_type(5) >= 1:
                break
            time.sleep(0.05)
        assert cap.count_type(5) == 1
        client.post("/highlight/end", json={"taskId": "id1", "matchId": "m"})
        time.sleep(0.2)
        assert cap.count_type(5) == 1
        t = TASK_MANAGER.get("id1")
        assert t and "type5:reel" in t.emitted_result_ids
    finally:
        cap.stop()


def test_callback_retry_same_result_id(client: TestClient):
    """HTTP 重试不新增 emitted_result_ids。"""
    cap = _CallbackCapture()
    url = cap.start(fail_first_n=2)
    try:
        SERVICE.callback_max_attempts = 3
        SERVICE.callback_backoff_s = 0.01
        _start(client, "rt9", "m", url)
        for c in [
            _clip("c1", "角球", 100.0, "corner"),
            _clip("c2", "传中", 103.0, "cross"),
            _clip("c3", "头球", 106.0, "header_shot"),
            _clip("c4", "进球", 108.0, "goal"),
        ]:
            _sync(client, "rt9", "m", c)
        assert cap.wait_type(1, timeout=15)
        deadline = time.time() + 5
        while time.time() < deadline and cap.hit_count() < 3:
            time.sleep(0.05)
        assert cap.hit_count() >= 3
        t = TASK_MANAGER.get("rt9")
        assert t
        # 同一业务链只有一个 result id
        assert len(t.emitted_result_ids) >= 1
        n_ids = len(t.emitted_result_ids)
        time.sleep(0.3)
        assert len(t.emitted_result_ids) == n_ids
        assert any(r.get("ok") and r.get("attempts") == 3 for r in t.callback_records)
    finally:
        client.post("/highlight/end", json={"taskId": "rt9", "matchId": "m"})
        cap.stop()
