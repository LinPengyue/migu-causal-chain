"""Prefix-replay adapter：每次只喂当前 prefix，内部调用现有 batch strip。

评测不内置触发/lookback；窗参来自算法 profile（strip 配置）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from causal_chain6.config import load_profile
from causal_chain6.online_strip_engine import OnlineStripEngine
from causal_chain6.schema.templates import CHAIN4_TEMPLATES
from causal_chain6.strip_pipeline import run_strip_highlights_events


def _clip_to_pred(clip: Dict[str, Any]) -> Dict[str, Any]:
    evs = clip.get("events") or []
    first = ""
    last = ""
    event_ids: List[str] = []
    event_keys: List[List[Any]] = []
    if evs:
        first = str(evs[0].get("type") or "")
        last = str(evs[-1].get("type") or "")
        for e in evs:
            eid = e.get("event_id")
            if eid is not None:
                event_ids.append(str(eid))
            if e.get("t_ms") is not None and e.get("type"):
                event_keys.append([int(e["t_ms"]), str(e["type"])])
    tid = clip.get("pred_chain_template_id") or clip.get("chain_template_id") or ""
    cat = clip.get("chain_category") or ""
    if not cat and tid in CHAIN4_TEMPLATES:
        cat = CHAIN4_TEMPLATES[tid]["category"]
    return {
        "chain_category": cat,
        "first_event": first,
        "last_event": last,
        "t0_ms": int(clip.get("t0_ms") or 0),
        "t1_ms": int(clip.get("t1_ms") or 0),
        "template_id": tid,
        "source": clip.get("source") or "",
        "event_ids": event_ids,
        "event_keys": event_keys,
    }


class AlgoStripAdapter:
    """V1：predict(prefix) → chains；底层 = causal_chain6.strip_pipeline。"""

    def __init__(
        self,
        *,
        profile_name: str = "production",
        model=None,
        processor=None,
        device: str = "cpu",
        use_llm: bool = False,
        use_sliding_recall: Optional[bool] = None,
        max_new_tokens: int = 512,
    ) -> None:
        self.profile = dict(load_profile(profile_name))
        self.profile.setdefault("llm", {})
        self.profile["llm"] = dict(self.profile.get("llm") or {})
        self.profile["llm"]["enabled"] = bool(use_llm and model is not None)
        self.model = model if use_llm else None
        self.processor = processor if use_llm else None
        self.device = device
        self.max_new_tokens = max_new_tokens

        strip_cfg = self.profile.get("strip") or {}
        self.pre_ms = int(strip_cfg.get("pre_ms", 120_000))
        self.post_ms = int(strip_cfg.get("post_ms", 60_000))
        self.window_ms = int(strip_cfg.get("window_ms", 180_000))
        self.step_ms = int(strip_cfg.get("step_ms", 90_000))
        self.min_margin = float(strip_cfg.get("min_margin", 0.08))
        self.min_prob_top1 = float(strip_cfg.get("min_prob_top1", 0.0))
        self.iou_dedupe = float(strip_cfg.get("iou_dedupe", 0.5))
        self.iou_recall = float(strip_cfg.get("iou_recall", 0.45))
        self.max_events = int(strip_cfg.get("max_events", 12))
        self.sliding_merge_mode = str(strip_cfg.get("sliding_merge_mode", "legacy") or "legacy")
        self.sliding_post_nms = str(strip_cfg.get("sliding_post_nms", "off") or "off")
        if use_sliding_recall is None:
            # 与 strip 管线默认一致：开滑窗召回（属算法行为，非评测触发器）
            self.use_sliding_recall = True
        else:
            self.use_sliding_recall = bool(use_sliding_recall)

    def predict(
        self,
        prefix: List[Dict[str, Any]],
        *,
        match_id: str = "stream",
    ) -> List[Dict[str, Any]]:
        """只根据当前 prefix 拆条；无未来事件。"""
        out = run_strip_highlights_events(
            events=prefix,
            match_id=match_id,
            profile=self.profile,
            model=self.model,
            processor=self.processor,
            device=self.device,
            max_new_tokens=self.max_new_tokens,
            pre_ms=self.pre_ms,
            post_ms=self.post_ms,
            window_ms=self.window_ms,
            step_ms=self.step_ms,
            min_margin=self.min_margin,
            min_prob_top1=self.min_prob_top1,
            iou_dedupe_thresh=self.iou_dedupe,
            iou_recall_thresh=self.iou_recall,
            max_events=self.max_events,
            use_sliding_recall=self.use_sliding_recall,
            template_whitelist=None,
            input_file=f"prefix:{match_id}:{len(prefix)}",
            sliding_merge_mode=self.sliding_merge_mode,
            sliding_post_nms=self.sliding_post_nms,
        )
        return [_clip_to_pred(c) for c in (out.get("clips") or [])]

    def config_snapshot(self) -> Dict[str, Any]:
        return {
            "adapter": "AlgoStripAdapter",
            "backend": "causal_chain6.strip_pipeline",
            "profile": self.profile.get("name"),
            "llm_enabled": bool(self.profile.get("llm", {}).get("enabled")),
            "classify_backend": (
                "chain4_agent+qwen" if self.profile.get("llm", {}).get("enabled") else "chain4_agent_rule"
            ),
            "qwen_scope": "template/category only; geometry/stream unchanged",
            "pre_ms": self.pre_ms,
            "post_ms": self.post_ms,
            "window_ms": self.window_ms,
            "step_ms": self.step_ms,
            "sliding_merge_mode": self.sliding_merge_mode,
            "sliding_post_nms": self.sliding_post_nms,
            "min_margin": self.min_margin,
            "use_sliding_recall": self.use_sliding_recall,
            "note": "窗参来自算法 profile.strip；评测不内置触发/lookback",
        }


class OnlineStripAdapter:
    """P3：stateful 在线拆条；feed 逐事件，predict(prefix) 兼容 prefix 接口。"""

    def __init__(
        self,
        *,
        profile_name: str = "production",
        model=None,
        processor=None,
        device: str = "cpu",
        use_llm: bool = False,
        use_sliding_recall: Optional[bool] = None,
        max_new_tokens: int = 512,
    ) -> None:
        self.profile = dict(load_profile(profile_name))
        self.profile.setdefault("llm", {})
        self.profile["llm"] = dict(self.profile.get("llm") or {})
        self.profile["llm"]["enabled"] = bool(use_llm and model is not None)
        self.model = model if use_llm else None
        self.processor = processor if use_llm else None
        self.device = device
        self.max_new_tokens = max_new_tokens

        strip_cfg = self.profile.get("strip") or {}
        self.pre_ms = int(strip_cfg.get("pre_ms", 120_000))
        self.post_ms = int(strip_cfg.get("post_ms", 60_000))
        self.window_ms = int(strip_cfg.get("window_ms", 180_000))
        self.step_ms = int(strip_cfg.get("step_ms", 90_000))
        self.min_margin = float(strip_cfg.get("min_margin", 0.08))
        self.min_prob_top1 = float(strip_cfg.get("min_prob_top1", 0.0))
        self.iou_dedupe = float(strip_cfg.get("iou_dedupe", 0.5))
        self.iou_recall = float(strip_cfg.get("iou_recall", 0.45))
        self.max_events = int(strip_cfg.get("max_events", 12))
        self.sliding_merge_mode = str(strip_cfg.get("sliding_merge_mode", "legacy") or "legacy")
        self.sliding_post_nms = str(strip_cfg.get("sliding_post_nms", "off") or "off")
        if use_sliding_recall is None:
            self.use_sliding_recall = True
        else:
            self.use_sliding_recall = bool(use_sliding_recall)

        self._engine: Optional[OnlineStripEngine] = None
        self._match_id = "stream"

    def _make_engine(self, match_id: str) -> OnlineStripEngine:
        return OnlineStripEngine(
            profile=self.profile,
            match_id=match_id,
            model=self.model,
            processor=self.processor,
            device=self.device,
            max_new_tokens=self.max_new_tokens,
            pre_ms=self.pre_ms,
            post_ms=self.post_ms,
            window_ms=self.window_ms,
            step_ms=self.step_ms,
            min_margin=self.min_margin,
            min_prob_top1=self.min_prob_top1,
            iou_dedupe=self.iou_dedupe,
            iou_recall=self.iou_recall,
            max_events=self.max_events,
            use_sliding_recall=self.use_sliding_recall,
            sliding_merge_mode=self.sliding_merge_mode,
            sliding_post_nms=self.sliding_post_nms,
        )

    def reset(self, *, match_id: str = "stream") -> None:
        self._match_id = match_id
        self._engine = self._make_engine(match_id)

    def feed(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        if self._engine is None:
            self.reset(match_id=self._match_id)
        clips = self._engine.feed(event)
        return [_clip_to_pred(c) for c in clips]

    def advance_time(self, t_ms: int) -> List[Dict[str, Any]]:
        if self._engine is None:
            self.reset(match_id=self._match_id)
        clips = self._engine.advance_time(t_ms)
        return [_clip_to_pred(c) for c in clips]

    def next_deadline_ms(self) -> Optional[int]:
        if self._engine is None:
            return None
        return self._engine.next_deadline_ms()

    @property
    def clock_ms(self) -> Optional[int]:
        if self._engine is None:
            return None
        return self._engine.clock_ms

    def flush(self) -> List[Dict[str, Any]]:
        if self._engine is None:
            return []
        clips = self._engine.flush()
        return [_clip_to_pred(c) for c in clips]

    def predict(
        self,
        prefix: List[Dict[str, Any]],
        *,
        match_id: str = "stream",
    ) -> List[Dict[str, Any]]:
        """兼容接口：重置后逐事件 feed 整个 prefix。"""
        self.reset(match_id=match_id)
        if not prefix:
            return []
        clips = self._engine.feed_many(list(prefix))
        return [_clip_to_pred(c) for c in clips]

    def config_snapshot(self) -> Dict[str, Any]:
        return {
            "adapter": "OnlineStripAdapter",
            "backend": "causal_chain6.online_strip_engine",
            "profile": self.profile.get("name"),
            "llm_enabled": bool(self.profile.get("llm", {}).get("enabled")),
            "classify_backend": (
                "chain4_agent+qwen" if self.profile.get("llm", {}).get("enabled") else "chain4_agent_rule"
            ),
            "qwen_scope": "template/category only; geometry/stream unchanged",
            "pre_ms": self.pre_ms,
            "post_ms": self.post_ms,
            "window_ms": self.window_ms,
            "step_ms": self.step_ms,
            "sliding_merge_mode": self.sliding_merge_mode,
            "sliding_post_nms": self.sliding_post_nms,
            "min_margin": self.min_margin,
            "use_sliding_recall": self.use_sliding_recall,
            "note": "P3.1 stateful online；feed+advance_time；predict=reset+feed_many+flush",
        }
