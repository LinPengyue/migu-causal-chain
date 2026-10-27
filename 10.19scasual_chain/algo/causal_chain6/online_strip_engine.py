"""P3/P3.1：在线 stateful 拆条引擎 — 逐事件输入 + 时钟推进 finalize。

因果约束：segment 仅在时间窗边界已观测到后才打分（不偷看未来）。
P3.1：advance_time(t_ms) 可在无新事件时关闭已到期 pending（不依赖下一事件到达）。
几何/打分/筛选逻辑与 batch strip_pipeline 对齐（merge_mode=none baseline）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from causal_chain2.segmentation_geom import ANCHOR_TYPES, GeoSegment
from causal_chain2.timeline_highlights import ScoredSegment, scored_to_clip_dict

from causal_chain6.strip_pipeline import finalize_strip_selection, score_segment_chain4


def _segment_key(seg: GeoSegment) -> Tuple[str, int, int]:
    return (seg.source, seg.i0, seg.i1)


@dataclass
class _PendingAnchor:
    anchor_i: int
    t_anchor: int
    close_ms: int
    i0: int
    i1: int


@dataclass
class _PendingSliding:
    start_ms: int
    end_ms: int
    i0: int
    i1: int


@dataclass
class OnlineStripEngine:
    """逐事件 feed，内部维护 geom/scored/final 状态；支持时钟推进。"""

    profile: Dict[str, Any]
    match_id: str = "online"
    model: Any = None
    processor: Any = None
    device: str = "cpu"
    max_new_tokens: int = 512
    pre_ms: int = 120_000
    post_ms: int = 60_000
    window_ms: int = 180_000
    step_ms: int = 90_000
    min_margin: float = 0.08
    min_prob_top1: float = 0.0
    iou_dedupe: float = 0.5
    iou_recall: float = 0.45
    max_events: Optional[int] = 12
    use_sliding_recall: bool = True
    template_whitelist: Optional[List[str]] = None
    sliding_merge_mode: str = "none"
    sliding_post_nms: str = "off"
    min_events: int = 2

    events: List[Dict[str, Any]] = field(default_factory=list)
    anchor_pending: Dict[int, _PendingAnchor] = field(default_factory=dict)
    sliding_pending: Dict[int, _PendingSliding] = field(default_factory=dict)
    anchor_scored: List[ScoredSegment] = field(default_factory=list)
    slide_scored: List[ScoredSegment] = field(default_factory=list)
    scored_keys: Set[Tuple[str, int, int]] = field(default_factory=set)
    _next_sliding_start: Optional[int] = None
    _t_min: Optional[int] = None
    _n_feeds: int = 0
    _clock_ms: Optional[int] = None

    def reset(self) -> None:
        self.events.clear()
        self.anchor_pending.clear()
        self.sliding_pending.clear()
        self.anchor_scored.clear()
        self.slide_scored.clear()
        self.scored_keys.clear()
        self._next_sliding_start = None
        self._t_min = None
        self._n_feeds = 0
        self._clock_ms = None

    @property
    def clock_ms(self) -> Optional[int]:
        return self._clock_ms

    def _event_horizon_ms(self) -> Optional[int]:
        """已观测事件的时间上界；滑窗 start 不可超过此值（对齐 batch prefix）。"""
        if not self.events:
            return None
        return int(self.events[-1]["t_ms"])

    def _times_types(self) -> Tuple[List[int], List[str]]:
        times = [int(e["t_ms"]) for e in self.events]
        types = [str(e["type"]) for e in self.events]
        return times, types

    def _make_anchor_pending(self, anchor_i: int) -> None:
        times, _ = self._times_types()
        t_anchor = times[anchor_i]
        close_ms = t_anchor + self.post_ms
        t0 = t_anchor - self.pre_ms
        n = len(times)
        i0 = next((k for k in range(n) if times[k] >= t0), 0)
        i1 = next((k for k in range(n - 1, -1, -1) if times[k] <= close_ms), n - 1)
        if i1 < i0 or i1 - i0 + 1 < self.min_events:
            return
        self.anchor_pending[anchor_i] = _PendingAnchor(
            anchor_i=anchor_i,
            t_anchor=t_anchor,
            close_ms=close_ms,
            i0=i0,
            i1=i1,
        )

    def _refresh_anchor_pending(self) -> None:
        times, _ = self._times_types()
        n = len(times)
        for p in list(self.anchor_pending.values()):
            t0 = p.t_anchor - self.pre_ms
            i0 = next((k for k in range(n) if times[k] >= t0), 0)
            i1 = next(
                (k for k in range(n - 1, -1, -1) if times[k] <= p.close_ms),
                n - 1,
            )
            p.i0, p.i1 = i0, i1

    def _schedule_sliding_windows(self, t_max: int) -> None:
        if self._t_min is None:
            return
        if self._next_sliding_start is None:
            self._next_sliding_start = self._t_min
        while self._next_sliding_start <= t_max:
            start = self._next_sliding_start
            if start not in self.sliding_pending:
                end = start + self.window_ms
                self.sliding_pending[start] = _PendingSliding(
                    start_ms=start,
                    end_ms=end,
                    i0=0,
                    i1=-1,
                )
            self._next_sliding_start += self.step_ms

    def _refresh_sliding_pending(self) -> None:
        if not self.events:
            return
        times, _ = self._times_types()
        n = len(times)
        for p in self.sliding_pending.values():
            i0 = next((k for k in range(n) if times[k] >= p.start_ms), 0)
            i1 = next(
                (k for k in range(n - 1, -1, -1) if times[k] <= p.end_ms),
                n - 1,
            )
            p.i0, p.i1 = i0, i1

    def _pending_to_geom(self, p: _PendingAnchor | _PendingSliding, source: str) -> Optional[GeoSegment]:
        times, types = self._times_types()
        if p.i1 < p.i0 or p.i1 - p.i0 + 1 < self.min_events:
            return None
        anchor_i = p.anchor_i if isinstance(p, _PendingAnchor) else None
        return GeoSegment(
            t0_ms=times[p.i0],
            t1_ms=times[p.i1],
            i0=p.i0,
            i1=p.i1,
            types=types[p.i0 : p.i1 + 1],
            source=source,
            anchor_i=anchor_i,
        )

    def _score_geom(self, seg: GeoSegment) -> None:
        key = _segment_key(seg)
        if key in self.scored_keys:
            return
        sc = score_segment_chain4(
            self.events,
            seg,
            profile=self.profile,
            model=self.model,
            processor=self.processor,
            device=self.device,
            max_new_tokens=self.max_new_tokens,
            max_events=self.max_events,
            match_id=self.match_id,
        )
        self.scored_keys.add(key)
        if seg.source == "anchor":
            self.anchor_scored.append(sc)
        else:
            self.slide_scored.append(sc)

    def _finalize_ready_anchors(self, t_now: int) -> None:
        done: List[int] = []
        for anchor_i, p in self.anchor_pending.items():
            if t_now < p.close_ms:
                continue
            seg = self._pending_to_geom(p, "anchor")
            if seg is not None:
                self._score_geom(seg)
            done.append(anchor_i)
        for anchor_i in done:
            del self.anchor_pending[anchor_i]

    def _finalize_ready_sliding(self, t_now: int) -> None:
        done: List[int] = []
        for start_ms, p in self.sliding_pending.items():
            if t_now < p.end_ms:
                continue
            seg = self._pending_to_geom(p, "sliding")
            if seg is not None:
                self._score_geom(seg)
            done.append(start_ms)
        for start_ms in done:
            del self.sliding_pending[start_ms]

    def _tick(self, t_ms: int) -> None:
        """把时钟推到 t_ms，并 finalize 所有已到期 pending。"""
        horizon = self._event_horizon_ms()
        sched_to = t_ms if horizon is None else min(t_ms, horizon)
        self._refresh_anchor_pending()
        if self.use_sliding_recall and self.sliding_merge_mode == "none":
            self._schedule_sliding_windows(sched_to)
            self._refresh_sliding_pending()
        self._finalize_ready_anchors(t_ms)
        if self.use_sliding_recall:
            self._finalize_ready_sliding(t_ms)
        self._clock_ms = int(t_ms)

    def next_deadline_ms(self) -> Optional[int]:
        """下一个需要时钟推进的 finalize 时刻（严格大于当前 clock）。"""
        clock = self._clock_ms
        cands: List[int] = []
        for p in self.anchor_pending.values():
            if clock is None or p.close_ms > clock:
                cands.append(int(p.close_ms))
        for p in self.sliding_pending.values():
            if clock is None or p.end_ms > clock:
                cands.append(int(p.end_ms))
        horizon = self._event_horizon_ms()
        if (
            self.use_sliding_recall
            and self.sliding_merge_mode == "none"
            and self._next_sliding_start is not None
            and horizon is not None
            and self._next_sliding_start <= horizon
        ):
            end = int(self._next_sliding_start) + int(self.window_ms)
            if clock is None or end > clock:
                cands.append(end)
        return min(cands) if cands else None

    def advance_time(self, t_ms: int) -> List[Dict[str, Any]]:
        """无新事件时推进时钟；关闭所有 close/end <= t_ms 的 pending。"""
        t_ms = int(t_ms)
        if self._clock_ms is not None and t_ms < self._clock_ms:
            raise ValueError(
                f"advance_time requires non-decreasing clock; got {t_ms} after {self._clock_ms}"
            )
        if self.events:
            last_t = int(self.events[-1]["t_ms"])
            if t_ms < last_t:
                raise ValueError(
                    f"advance_time cannot go before last event; got {t_ms} < {last_t}"
                )
        if not self.events:
            self._clock_ms = t_ms
            return self._current_clips()
        self._tick(t_ms)
        return self._current_clips()

    def flush(self) -> List[Dict[str, Any]]:
        """流结束：强制 finalize 仍 pending 的 segment（与 batch 终局 prefix 对齐）。"""
        self._refresh_anchor_pending()
        if self.use_sliding_recall:
            self._refresh_sliding_pending()
        for anchor_i in list(self.anchor_pending.keys()):
            p = self.anchor_pending[anchor_i]
            seg = self._pending_to_geom(p, "anchor")
            if seg is not None:
                self._score_geom(seg)
            del self.anchor_pending[anchor_i]
        for start_ms in list(self.sliding_pending.keys()):
            p = self.sliding_pending[start_ms]
            seg = self._pending_to_geom(p, "sliding")
            if seg is not None:
                self._score_geom(seg)
            del self.sliding_pending[start_ms]
        if self.events:
            self._clock_ms = max(int(self._clock_ms or 0), int(self.events[-1]["t_ms"]))
        return self._current_clips()

    def _current_clips(self) -> List[Dict[str, Any]]:
        combined = finalize_strip_selection(
            anchor_scored=self.anchor_scored,
            slide_scored=self.slide_scored,
            min_margin=self.min_margin,
            min_prob_top1=self.min_prob_top1,
            iou_dedupe_thresh=self.iou_dedupe,
            iou_recall_thresh=self.iou_recall,
            use_sliding_recall=self.use_sliding_recall,
            template_whitelist=self.template_whitelist,
            sliding_post_nms=self.sliding_post_nms,
        )
        return [
            scored_to_clip_dict(s, f"clip{i:02d}", events=self.events)
            for i, s in enumerate(combined)
        ]

    def feed(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """摄入单个事件，返回当前 candidate chains（clip dict 列表）。"""
        ev = dict(event)
        if ev.get("t_ms") is None or not ev.get("type"):
            return self._current_clips()

        t_now = int(ev["t_ms"])
        if self.events:
            last_t = int(self.events[-1]["t_ms"])
            if t_now < last_t:
                raise ValueError(
                    f"online strip requires non-decreasing t_ms; got {t_now} after {last_t}"
                )

        idx = len(self.events)
        ev.setdefault("order", idx)
        ev.setdefault("event_id", ev.get("event_id") or f"{self.match_id}_e{idx:04d}")
        self.events.append(ev)
        self._n_feeds += 1

        if self._t_min is None:
            self._t_min = t_now

        if ev["type"] in ANCHOR_TYPES:
            self._make_anchor_pending(idx)

        self._tick(t_now)
        return self._current_clips()

    def feed_many(
        self, events: List[Dict[str, Any]], *, flush_at_end: bool = True
    ) -> List[Dict[str, Any]]:
        preds: List[Dict[str, Any]] = []
        n = len(events)
        for i, e in enumerate(events):
            preds = self.feed(e)
            next_t = int(events[i + 1]["t_ms"]) if i + 1 < n else None
            while True:
                d = self.next_deadline_ms()
                if d is None:
                    break
                if next_t is not None and d >= next_t:
                    break
                preds = self.advance_time(d)
        if flush_at_end and events:
            # 末事件之后继续推进到期窗，再 flush 对齐 batch 终局
            while True:
                d = self.next_deadline_ms()
                if d is None:
                    break
                preds = self.advance_time(d)
            preds = self.flush()
        return preds

    def snapshot(self) -> Dict[str, Any]:
        return {
            "n_events": len(self.events),
            "n_feeds": self._n_feeds,
            "clock_ms": self._clock_ms,
            "anchor_pending": len(self.anchor_pending),
            "sliding_pending": len(self.sliding_pending),
            "anchor_scored": len(self.anchor_scored),
            "slide_scored": len(self.slide_scored),
            "n_clips": len(self._current_clips()),
        }
