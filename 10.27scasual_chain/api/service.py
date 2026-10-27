"""业务编排：start / sync / end + deadline timer 推进（不改算法判定）。"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from api.adapters import (
    DEFAULT_ADAPTER_CONFIG,
    AdapterConfig,
    clip_to_algo_event,
    post_match_type5_body,
    select_new_strip_callbacks,
)
from api.callback import post_callbacks
from api.highlight_build import build_highlight_clips_from_events
from api.task_manager import TASK_MANAGER, TaskManager, TaskState

logger = logging.getLogger("api.service")


def _ensure_algo_path() -> None:
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    algo = str(root / "algo")
    if algo not in sys.path:
        sys.path.insert(0, algo)


class HighlightService:
    def __init__(
        self,
        *,
        task_manager: TaskManager = TASK_MANAGER,
        adapter_cfg: Optional[AdapterConfig] = None,
        profile_name: str = "production",
        use_llm: bool = False,
        device: str = "cpu",
        callback_timeout_s: float = 5.0,
        callback_max_attempts: int = 3,
        callback_backoff_s: float = 0.2,
    ) -> None:
        _ensure_algo_path()
        from causal_chain6.config import load_profile as load_c6_profile
        from causal_chain6.online_strip_engine import OnlineStripEngine
        from causal_chain8.config import load_profile as load_c8_profile

        self.tm = task_manager
        self.adapter_cfg = adapter_cfg or DEFAULT_ADAPTER_CONFIG
        self.profile_name = profile_name
        self.use_llm = use_llm
        self.device = device
        self.callback_timeout_s = callback_timeout_s
        self.callback_max_attempts = callback_max_attempts
        self.callback_backoff_s = callback_backoff_s

        self._c6_profile = dict(load_c6_profile(profile_name))
        self._c6_profile.setdefault("llm", {})
        self._c6_profile["llm"] = dict(self._c6_profile.get("llm") or {})
        self._c6_profile["llm"]["enabled"] = bool(use_llm)

        self._c8_profile = dict(load_c8_profile(profile_name))
        self._c8_profile.setdefault("llm", {})
        self._c8_profile["llm"] = dict(self._c8_profile.get("llm") or {})
        self._c8_profile["llm"]["enabled"] = bool(use_llm)

        self._model = None
        self._processor = None
        self._OnlineStripEngine = OnlineStripEngine

        strip_cfg = self._c6_profile.get("strip") or {}
        self._engine_kwargs = dict(
            profile=self._c6_profile,
            model=self._model,
            processor=self._processor,
            device=device,
            pre_ms=int(strip_cfg.get("pre_ms", 120_000)),
            post_ms=int(strip_cfg.get("post_ms", 60_000)),
            window_ms=int(strip_cfg.get("window_ms", 180_000)),
            step_ms=int(strip_cfg.get("step_ms", 90_000)),
            min_margin=float(strip_cfg.get("min_margin", 0.08)),
            min_prob_top1=float(strip_cfg.get("min_prob_top1", 0.0)),
            iou_dedupe=float(strip_cfg.get("iou_dedupe", 0.5)),
            iou_recall=float(strip_cfg.get("iou_recall", 0.45)),
            max_events=int(strip_cfg.get("max_events", 12)),
            use_sliding_recall=True,
            sliding_merge_mode=str(strip_cfg.get("sliding_merge_mode", "none") or "none"),
            sliding_post_nms=str(strip_cfg.get("sliding_post_nms", "off") or "off"),
        )

    def _new_engine(self, match_id: str):
        return self._OnlineStripEngine(match_id=match_id, **self._engine_kwargs)

    def start(self, task_id: str, match_id: str, callback_url: str) -> Tuple[str, str]:
        try:
            task, created = self.tm.create_or_get(
                task_id=task_id,
                match_id=match_id,
                callback_url=callback_url,
                engine_factory=self._new_engine,
            )
        except ValueError as exc:
            return "1", str(exc)
        if not created:
            with task.lock:
                if task.status == "running":
                    task.callback_url = callback_url
            logger.info("start idempotent taskId=%s matchId=%s", task_id, match_id)
        else:
            logger.info("start created taskId=%s matchId=%s", task_id, match_id)
        return "0", "success"

    def sync(self, task_id: str, match_id: str, clip: Dict[str, Any]) -> Tuple[str, str]:
        task = self.tm.get_for_pair(task_id, match_id)
        if task is None:
            return "1", f"task not found: taskId={task_id} matchId={match_id}"

        new_bodies: List[Dict[str, Any]] = []
        callback_url = ""

        with task.lock:
            if task.status != "running":
                return "1", f"task not running (status={task.status})"

            clip_id = str(clip["clipId"])
            if clip_id in task.received_clip_ids:
                logger.info("sync duplicate clipId=%s skipped", clip_id)
                return "0", "success"

            order = len(task.events)
            ev, err = clip_to_algo_event(
                clip,
                cfg=self.adapter_cfg,
                order=order,
                task_id=task_id,
                match_id=match_id,
            )
            if err or ev is None:
                return "1", err or "clip conversion failed"
            t_ms = int(ev["t_ms"])

            if self.adapter_cfg.reject_out_of_order and task.last_accepted_t_ms is not None:
                if t_ms < int(task.last_accepted_t_ms):
                    return (
                        "1",
                        f"out-of-order event rejected: eventTime={t_ms} < last={task.last_accepted_t_ms}",
                    )

            callback_url = task.callback_url
            # 事务式：算法成功后再 commit received_clip_ids/events；失败完整 rollback
            prev_last_t = task.last_accepted_t_ms
            prev_strip = list(task.strip_preds or [])
            engine_snapshot_n = len(task.engine.events) if task.engine is not None else 0

            try:
                if task.engine is None:
                    task.engine = self._new_engine(match_id)
                preds = task.engine.feed(dict(ev))
                while True:
                    d = task.engine.next_deadline_ms()
                    if d is None or d > t_ms:
                        break
                    preds = task.engine.advance_time(d)

                # commit
                task.received_clip_ids.add(clip_id)
                task.clip_meta[clip_id] = dict(clip)
                task.events.append(ev)
                task.last_accepted_t_ms = t_ms
                task.strip_preds = list(preds or [])

                bodies, new_ids = select_new_strip_callbacks(
                    task.strip_preds,
                    task_id=task_id,
                    match_id=match_id,
                    known_clip_ids=list(task.received_clip_ids),
                    events=list(task.events),
                    emitted_result_ids=task.emitted_result_ids,
                    cfg=self.adapter_cfg,
                )
                for rid in new_ids:
                    task.emitted_result_ids.add(rid)
                new_bodies = bodies
                self._reschedule_deadline_locked(task)
            except Exception as exc:  # noqa: BLE001
                logger.exception("sync algorithm error taskId=%s; rolling back clipId=%s", task_id, clip_id)
                # rollback：不留下 clipId，保证可重试
                task.received_clip_ids.discard(clip_id)
                task.clip_meta.pop(clip_id, None)
                task.events = [e for e in task.events if str(e.get("event_id")) != clip_id]
                task.last_accepted_t_ms = prev_last_t
                task.strip_preds = prev_strip
                # 引擎若已吃进该事件：重建并重放已 commit 事件（不含失败 clip）
                if task.engine is not None and len(task.engine.events) > engine_snapshot_n:
                    try:
                        task.engine = self._new_engine(match_id)
                        if task.events:
                            task.engine.feed_many(
                                [dict(e) for e in task.events],
                                flush_at_end=False,
                            )
                            task.strip_preds = list(task.engine._current_clips() or [])
                    except Exception:  # noqa: BLE001
                        logger.exception("engine rollback rebuild failed taskId=%s", task_id)
                        task.engine = self._new_engine(match_id)
                        task.strip_preds = []
                return "1", f"algorithm error: {exc}"

        if new_bodies:
            self._spawn_callbacks(task, callback_url, new_bodies)
        return "0", "success"

    def end(self, task_id: str, match_id: str) -> Tuple[str, str]:
        task = self.tm.get_for_pair(task_id, match_id)
        if task is None:
            return "1", f"task not found: taskId={task_id} matchId={match_id}"

        with task.lock:
            if task.status == "finished":
                logger.info("end idempotent taskId=%s", task_id)
                return "0", "success"
            if task.status == "stopping":
                return "0", "success"
            task.status = "stopping"
            task.cancel_timers()
            if task.type5_emitted or "type5:reel" in task.emitted_result_ids:
                # 已发送过 type=5（异常恢复路径）；仍允许 flush 补 1~4
                pass
            events_snapshot = [dict(e) for e in task.events]
            clip_ids = list(task.received_clip_ids)
            callback_url = task.callback_url
            engine = task.engine
            emitted = set(task.emitted_result_ids)
            already_type5 = bool(task.type5_emitted) or ("type5:reel" in emitted)

        try:
            strip_preds: List[Dict[str, Any]] = []
            if engine is not None:
                try:
                    while engine.next_deadline_ms() is not None:
                        engine.advance_time(engine.next_deadline_ms())
                    strip_preds = list(engine.flush() or [])
                except Exception:  # noqa: BLE001
                    logger.exception("flush online engine failed taskId=%s", task_id)
                    strip_preds = []

            flush_bodies, new_ids = select_new_strip_callbacks(
                strip_preds,
                task_id=task_id,
                match_id=match_id,
                known_clip_ids=clip_ids,
                events=events_snapshot,
                emitted_result_ids=emitted,
                cfg=self.adapter_cfg,
            )

            reel_clips = self._build_highlights(events_snapshot, match_id=match_id)
            type5 = None
            if not already_type5:
                type5 = post_match_type5_body(
                    task_id=task_id,
                    match_id=match_id,
                    reel_clips=reel_clips,
                    known_clip_ids=clip_ids,
                    events=events_snapshot,
                    cfg=self.adapter_cfg,
                )

            end_bodies = list(flush_bodies)
            notes: List[str] = []
            if type5 is not None:
                end_bodies.append(type5)
            elif already_type5:
                notes.append("type5 already emitted; skip duplicate")
            else:
                notes.append("highlightType=5 disabled by AdapterConfig.emit_highlight_type5=False")

            with task.lock:
                task.strip_preds = strip_preds
                task.generated_results = list(reel_clips)
                for rid in new_ids:
                    task.emitted_result_ids.add(rid)
                if type5 is not None:
                    task.emitted_result_ids.add("type5:reel")
                    task.type5_emitted = True
                task.protocol_notes.extend(notes)

            if end_bodies:
                records = post_callbacks(
                    callback_url,
                    end_bodies,
                    timeout_s=self.callback_timeout_s,
                    max_attempts=self.callback_max_attempts,
                    backoff_s=self.callback_backoff_s,
                )
                with task.lock:
                    task.callback_records.extend(records)

            with task.lock:
                task.status = "finished"
            return "0", "success"
        except Exception as exc:  # noqa: BLE001
            logger.exception("end failed taskId=%s", task_id)
            with task.lock:
                task.status = "failed"
            return "1", f"end failed: {exc}"

    def _wall_wait_s(self, deadline_ms: int, last_t_ms: int) -> float:
        cfg = self.adapter_cfg
        delta = max(0, int(deadline_ms) - int(last_t_ms))
        scale = float(cfg.media_ms_per_wall_second) or 1000.0
        wall = delta / scale
        return max(cfg.deadline_timer_min_wall_s, min(wall, cfg.deadline_timer_max_wall_s))

    def _reschedule_deadline_locked(self, task: TaskState) -> None:
        """持有 task.lock 时调用：取消旧 timer，为 next_deadline 注册新 timer。"""
        if not self.adapter_cfg.enable_deadline_timer:
            return
        if task.status != "running" or task.engine is None:
            return
        task.cancel_timers()
        d = task.engine.next_deadline_ms()
        if d is None:
            return
        last_t = int(task.last_accepted_t_ms or 0)
        if d <= last_t:
            wall_s = self.adapter_cfg.deadline_timer_min_wall_s
        else:
            wall_s = self._wall_wait_s(d, last_t)
        task.scheduled_deadline_ms = int(d)
        timer = threading.Timer(wall_s, self._on_deadline_timer, args=(task.task_id, int(d)))
        timer.daemon = True
        task.timers.append(timer)
        timer.start()
        logger.info(
            "deadline timer scheduled taskId=%s deadline_ms=%s wall_s=%.3f "
            "(media_ms_per_wall_second=%s; eventTime=media timeline, not HTTP arrival)",
            task.task_id,
            d,
            wall_s,
            self.adapter_cfg.media_ms_per_wall_second,
        )

    def _on_deadline_timer(self, task_id: str, expected_deadline_ms: int) -> None:
        """墙钟到期：advance_time 闭合窗；若有新链则 callback；再预约下一 deadline。"""
        task = self.tm.get(task_id)
        if task is None:
            return

        new_bodies: List[Dict[str, Any]] = []
        callback_url = ""

        with task.lock:
            if task.status != "running" or task.engine is None:
                return
            # 过期 timer：预约已被更新/取消，不得推进新的 deadline
            if task.scheduled_deadline_ms != int(expected_deadline_ms):
                logger.info(
                    "stale deadline timer ignored taskId=%s expected=%s scheduled=%s",
                    task_id,
                    expected_deadline_ms,
                    task.scheduled_deadline_ms,
                )
                return
            try:
                d = task.engine.next_deadline_ms()
                preds: List[Dict[str, Any]] = list(task.strip_preds or [])
                if d is not None:
                    preds = list(task.engine.advance_time(int(d)) or [])
                task.strip_preds = list(preds or [])
                bodies, new_ids = select_new_strip_callbacks(
                    task.strip_preds,
                    task_id=task.task_id,
                    match_id=task.match_id,
                    known_clip_ids=list(task.received_clip_ids),
                    events=list(task.events),
                    emitted_result_ids=task.emitted_result_ids,
                    cfg=self.adapter_cfg,
                )
                for rid in new_ids:
                    task.emitted_result_ids.add(rid)
                new_bodies = bodies
                callback_url = task.callback_url
                self._reschedule_deadline_locked(task)
            except Exception:  # noqa: BLE001
                logger.exception("deadline timer failed taskId=%s", task_id)
                return

        if new_bodies:
            self._spawn_callbacks(task, callback_url, new_bodies)

    def _build_highlights(self, events: List[Dict[str, Any]], *, match_id: str) -> List[Any]:
        _ensure_algo_path()
        if not events:
            return []
        clips, _stats = build_highlight_clips_from_events(
            events,
            match_id=match_id,
            profile=self._c8_profile,
            model=self._model,
            processor=self._processor,
            device=self.device,
            drop_t2=False,
        )
        return list(clips or [])

    def _spawn_callbacks(
        self,
        task: TaskState,
        callback_url: str,
        bodies: List[Dict[str, Any]],
    ) -> None:
        def _worker() -> None:
            try:
                records = post_callbacks(
                    callback_url,
                    bodies,
                    timeout_s=self.callback_timeout_s,
                    max_attempts=self.callback_max_attempts,
                    backoff_s=self.callback_backoff_s,
                )
                with task.lock:
                    task.callback_records.extend(records)
            except Exception:  # noqa: BLE001
                logger.exception("callback worker crashed taskId=%s", task.task_id)
                with task.lock:
                    task.callback_records.append(
                        {
                            "ok": False,
                            "callback_failed": True,
                            "error": "callback worker crashed",
                            "url": callback_url,
                        }
                    )

        threading.Thread(
            target=_worker,
            name=f"callback-{task.task_id}",
            daemon=True,
        ).start()

    def debug_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        t = self.tm.get(task_id)
        return t.snapshot() if t else None


SERVICE = HighlightService()
