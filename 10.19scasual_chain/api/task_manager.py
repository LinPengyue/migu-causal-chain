"""线程安全的内存任务表（第一版不上库；单 worker only）。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class TaskState:
    task_id: str
    match_id: str
    callback_url: str
    status: str = "running"  # running | stopping | finished | failed
    events: List[Dict[str, Any]] = field(default_factory=list)
    received_clip_ids: Set[str] = field(default_factory=set)
    clip_meta: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    engine: Any = None
    strip_preds: List[Dict[str, Any]] = field(default_factory=list)
    generated_results: List[Any] = field(default_factory=list)
    emitted_result_ids: Set[str] = field(default_factory=set)
    type5_emitted: bool = False
    callback_records: List[Dict[str, Any]] = field(default_factory=list)
    protocol_notes: List[str] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)
    last_accepted_t_ms: Optional[int] = None
    # 每 task 独立的 deadline timer 列表（end 时全部 cancel）
    timers: List[threading.Timer] = field(default_factory=list)
    scheduled_deadline_ms: Optional[int] = None

    def cancel_timers(self) -> None:
        for t in list(self.timers):
            try:
                t.cancel()
            except Exception:  # noqa: BLE001
                pass
        self.timers.clear()
        self.scheduled_deadline_ms = None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "match_id": self.match_id,
            "status": self.status,
            "n_events": len(self.events),
            "n_clip_ids": len(self.received_clip_ids),
            "n_results": len(self.generated_results),
            "n_emitted": len(self.emitted_result_ids),
            "callback_records": list(self.callback_records),
            "protocol_notes": list(self.protocol_notes),
            "scheduled_deadline_ms": self.scheduled_deadline_ms,
        }


class TaskManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_task: Dict[str, TaskState] = {}
        self._pair_index: Dict[tuple, str] = {}

    def get(self, task_id: str) -> Optional[TaskState]:
        with self._lock:
            return self._by_task.get(task_id)

    def get_for_pair(self, task_id: str, match_id: str) -> Optional[TaskState]:
        with self._lock:
            t = self._by_task.get(task_id)
            if t is None or t.match_id != match_id:
                return None
            return t

    def create_or_get(
        self,
        *,
        task_id: str,
        match_id: str,
        callback_url: str,
        engine_factory,
    ) -> tuple[TaskState, bool]:
        with self._lock:
            existing = self._by_task.get(task_id)
            if existing is not None:
                if existing.match_id != match_id:
                    raise ValueError(
                        f"taskId {task_id!r} already bound to matchId {existing.match_id!r}"
                    )
                return existing, False

            pair = (task_id, match_id)
            if pair in self._pair_index:
                return self._by_task[self._pair_index[pair]], False

            task = TaskState(
                task_id=task_id,
                match_id=match_id,
                callback_url=callback_url,
                engine=engine_factory(match_id),
            )
            self._by_task[task_id] = task
            self._pair_index[pair] = task_id
            return task, True

    def clear(self) -> None:
        with self._lock:
            for t in self._by_task.values():
                t.cancel_timers()
            self._by_task.clear()
            self._pair_index.clear()


TASK_MANAGER = TaskManager()
