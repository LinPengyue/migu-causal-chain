"""远程 OpenAI-compatible LLM/VLM Provider（咪咕交付生产路径）。

- Chat Completions（文本规划 + 多模态视觉）
- 独立 Planner / Vision 模型与 URL/密钥
- 超时、重试、简单限流、失败降级
- Token/成本统计与响应缓存
- 默认 mock 不计费；真实调用需显式开关
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

INTEGRATION_NOTES = """
Story Video Agent remote API (Phase 2B production path):
  STORY_LLM_BASE_URL / OPENAI_BASE_URL   e.g. https://api.openai.com/v1
  STORY_LLM_API_KEY  / OPENAI_API_KEY
  STORY_LLM_MODEL                       planner model id
  STORY_VLM_BASE_URL                    optional; defaults to LLM base
  STORY_VLM_API_KEY                     optional; defaults to LLM key
  STORY_VLM_MODEL                       vision model id
  STORY_LLM_TIMEOUT_SEC                 default 60
  STORY_LLM_MAX_RETRIES                 default 2
  STORY_LLM_RPM                         soft rate limit (requests/min), default 30
  STORY_API_ENABLE=1                    allow real HTTP calls
  STORY_API_SMOKE=1                     enable billed smoke tests in unittest

No local model download. Mock is default when ENABLE is unset or key missing.
""".strip()

# 粗算默认单价（USD / 1M tokens）；可用环境覆盖；仅用于统计，非账单
_DEFAULT_PRICE = {
    "prompt_per_mtok": float(os.environ.get("STORY_LLM_PRICE_PROMPT", "0.15")),
    "completion_per_mtok": float(os.environ.get("STORY_LLM_PRICE_COMPLETION", "0.60")),
}


@dataclass
class EndpointConfig:
    role: str  # planner | vision
    base_url: str
    api_key: str
    model: str
    timeout_sec: float = 60.0
    max_retries: int = 2
    rpm: float = 30.0

    def configured(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "base_url": self.base_url,
            "model": self.model,
            "timeout_sec": self.timeout_sec,
            "max_retries": self.max_retries,
            "rpm": self.rpm,
            "api_key_set": bool(self.api_key),
        }


@dataclass
class ApiCallRecord:
    role: str
    model: str
    ok: bool
    elapsed_sec: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    est_cost_usd: float = 0.0
    cached: bool = False
    error: str = ""
    http_status: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ApiUsageStats:
    calls: List[ApiCallRecord] = field(default_factory=list)

    def add(self, row: ApiCallRecord) -> None:
        self.calls.append(row)

    def summary(self) -> Dict[str, Any]:
        ok = [c for c in self.calls if c.ok]
        fail = [c for c in self.calls if not c.ok]
        return {
            "calls": len(self.calls),
            "ok": len(ok),
            "failures": len(fail),
            "cached_hits": sum(1 for c in self.calls if c.cached),
            "prompt_tokens": sum(c.prompt_tokens for c in self.calls),
            "completion_tokens": sum(c.completion_tokens for c in self.calls),
            "total_tokens": sum(c.total_tokens for c in self.calls),
            "est_cost_usd": round(sum(c.est_cost_usd for c in self.calls), 6),
            "elapsed_sec": round(sum(c.elapsed_sec for c in self.calls), 4),
            "by_role": {
                role: {
                    "calls": sum(1 for c in self.calls if c.role == role),
                    "tokens": sum(c.total_tokens for c in self.calls if c.role == role),
                    "est_cost_usd": round(
                        sum(c.est_cost_usd for c in self.calls if c.role == role), 6
                    ),
                }
                for role in sorted({c.role for c in self.calls})
            },
            "records": [c.to_dict() for c in self.calls[-20:]],
        }


class _RateLimiter:
    def __init__(self, rpm: float) -> None:
        self.min_interval = 60.0 / max(rpm, 0.1)
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
            self._last = time.monotonic()


def _env(*names: str, default: str = "") -> str:
    for name in names:
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    return default


def load_endpoint_configs() -> Dict[str, EndpointConfig]:
    timeout = float(_env("STORY_LLM_TIMEOUT_SEC", default="60") or 60)
    retries = int(float(_env("STORY_LLM_MAX_RETRIES", default="2") or 2))
    rpm = float(_env("STORY_LLM_RPM", default="30") or 30)
    base = _env("STORY_LLM_BASE_URL", "OPENAI_BASE_URL").rstrip("/")
    key = _env("STORY_LLM_API_KEY", "OPENAI_API_KEY")
    planner_model = _env("STORY_LLM_MODEL", "OPENAI_MODEL")
    vbase = _env("STORY_VLM_BASE_URL", default=base).rstrip("/")
    vkey = _env("STORY_VLM_API_KEY", default=key)
    vmodel = _env("STORY_VLM_MODEL", default=planner_model)
    return {
        "planner": EndpointConfig(
            role="planner",
            base_url=base,
            api_key=key,
            model=planner_model,
            timeout_sec=timeout,
            max_retries=retries,
            rpm=rpm,
        ),
        "vision": EndpointConfig(
            role="vision",
            base_url=vbase,
            api_key=vkey,
            model=vmodel,
            timeout_sec=timeout,
            max_retries=retries,
            rpm=rpm,
        ),
    }


def api_enabled() -> bool:
    return (os.environ.get("STORY_API_ENABLE") or "").strip() in ("1", "true", "TRUE", "yes")


def smoke_enabled() -> bool:
    return (os.environ.get("STORY_API_SMOKE") or "").strip() in ("1", "true", "TRUE", "yes")


def _estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return (
        prompt_tokens / 1_000_000.0 * _DEFAULT_PRICE["prompt_per_mtok"]
        + completion_tokens / 1_000_000.0 * _DEFAULT_PRICE["completion_per_mtok"]
    )


def _encode_image(path: Path) -> str:
    data = path.read_bytes()
    import base64

    b64 = base64.b64encode(data).decode("ascii")
    suffix = path.suffix.lower().lstrip(".") or "jpeg"
    mime = "image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}"
    return f"data:{mime};base64,{b64}"


class ApiProvider:
    """统一远程 API 客户端；未启用或未配置时走 mock。"""

    def __init__(
        self,
        *,
        force_mock: bool = False,
        configs: Optional[Dict[str, EndpointConfig]] = None,
    ) -> None:
        self.configs = configs or load_endpoint_configs()
        self.force_mock = force_mock or not api_enabled()
        self.stats = ApiUsageStats()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._limiters = {
            role: _RateLimiter(cfg.rpm) for role, cfg in self.configs.items()
        }
        self.notes = INTEGRATION_NOTES

    def status(self) -> Dict[str, Any]:
        return {
            "api_enabled": api_enabled() and not self.force_mock,
            "force_mock": self.force_mock,
            "planner": self.configs["planner"].to_dict(),
            "vision": self.configs["vision"].to_dict(),
            "planner_ready": self.configs["planner"].configured() and not self.force_mock,
            "vision_ready": self.configs["vision"].configured() and not self.force_mock,
            "notes": self.notes,
            "usage": self.stats.summary(),
        }

    def chat(
        self,
        *,
        role: str,
        messages: Sequence[Dict[str, Any]],
        temperature: float = 0.1,
        cache_key: Optional[str] = None,
        mock_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        cfg = self.configs[role]
        if cache_key and cache_key in self._cache:
            cached = dict(self._cache[cache_key])
            cached["cached"] = True
            self.stats.add(
                ApiCallRecord(
                    role=role,
                    model=cfg.model or "mock",
                    ok=True,
                    elapsed_sec=0.0,
                    cached=True,
                    prompt_tokens=int((cached.get("usage") or {}).get("prompt_tokens") or 0),
                    completion_tokens=int(
                        (cached.get("usage") or {}).get("completion_tokens") or 0
                    ),
                    total_tokens=int((cached.get("usage") or {}).get("total_tokens") or 0),
                )
            )
            return cached

        use_mock = self.force_mock or not cfg.configured()
        if use_mock:
            content = mock_content if mock_content is not None else '{"ok": true, "mock": true}'
            result = {
                "content": content,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "model": "mock",
                "provider": "mock",
                "cached": False,
            }
            self.stats.add(
                ApiCallRecord(
                    role=role, model="mock", ok=True, elapsed_sec=0.0, cached=False
                )
            )
            if cache_key:
                self._cache[cache_key] = result
            return result

        last_err = ""
        http_status = 0
        t0 = time.perf_counter()
        for attempt in range(cfg.max_retries + 1):
            try:
                self._limiters[role].wait()
                payload = self._post_chat(
                    cfg, messages=messages, temperature=temperature
                )
                elapsed = time.perf_counter() - t0
                usage = payload.get("usage") or {}
                pt = int(usage.get("prompt_tokens") or 0)
                ct = int(usage.get("completion_tokens") or 0)
                tt = int(usage.get("total_tokens") or (pt + ct))
                choices = payload.get("choices") or []
                if not choices:
                    raise RuntimeError("empty choices")
                content = str((choices[0].get("message") or {}).get("content") or "")
                result = {
                    "content": content,
                    "usage": {
                        "prompt_tokens": pt,
                        "completion_tokens": ct,
                        "total_tokens": tt,
                    },
                    "model": cfg.model,
                    "provider": "openai_compatible",
                    "cached": False,
                }
                self.stats.add(
                    ApiCallRecord(
                        role=role,
                        model=cfg.model,
                        ok=True,
                        elapsed_sec=elapsed,
                        prompt_tokens=pt,
                        completion_tokens=ct,
                        total_tokens=tt,
                        est_cost_usd=_estimate_cost(pt, ct),
                        http_status=200,
                    )
                )
                if cache_key:
                    self._cache[cache_key] = result
                return result
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                if isinstance(exc, urllib.error.HTTPError):
                    http_status = int(exc.code)
                if attempt >= cfg.max_retries:
                    break
                time.sleep(0.4 * (2**attempt))

        elapsed = time.perf_counter() - t0
        self.stats.add(
            ApiCallRecord(
                role=role,
                model=cfg.model,
                ok=False,
                elapsed_sec=elapsed,
                error=last_err,
                http_status=http_status,
            )
        )
        # 失败降级：返回 mock 标记
        return {
            "content": mock_content
            if mock_content is not None
            else json.dumps({"error": last_err, "degraded": True}),
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "model": cfg.model,
            "provider": "degraded_mock",
            "cached": False,
            "error": last_err,
        }

    def _post_chat(
        self,
        cfg: EndpointConfig,
        *,
        messages: Sequence[Dict[str, Any]],
        temperature: float,
    ) -> Dict[str, Any]:
        body = {
            "model": cfg.model,
            "temperature": temperature,
            "messages": list(messages),
        }
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        }
        req = urllib.request.Request(
            f"{cfg.base_url}/chat/completions",
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=cfg.timeout_sec) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {detail[:400]}") from exc

    def plan_decision(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        mock_decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        key = hashlib.sha1(
            (system_prompt + "\n" + user_prompt).encode("utf-8")
        ).hexdigest()[:24]
        result = self.chat(
            role="planner",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            cache_key=f"plan:{key}",
            mock_content=json.dumps(mock_decision, ensure_ascii=False),
        )
        return result

    def vision_json(
        self,
        *,
        prompt: str,
        frame_paths: Sequence[Path],
        frame_ids: Sequence[str],
        mock_obj: Dict[str, Any],
    ) -> Dict[str, Any]:
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for path, fid in zip(frame_paths, frame_ids):
            content.append({"type": "text", "text": f"frame_id={fid}"})
            if Path(path).is_file():
                content.append(
                    {"type": "image_url", "image_url": {"url": _encode_image(Path(path))}}
                )
        # 缓存键不含像素，用路径+mtime
        digest = hashlib.sha1()
        digest.update(prompt.encode("utf-8"))
        for path, fid in zip(frame_paths, frame_ids):
            p = Path(path)
            digest.update(fid.encode("utf-8"))
            if p.is_file():
                digest.update(str(p.stat().st_mtime_ns).encode("utf-8"))
        result = self.chat(
            role="vision",
            messages=[
                {"role": "system", "content": "Reply with strict JSON only."},
                {"role": "user", "content": content},
            ],
            cache_key=f"vision:{digest.hexdigest()[:24]}",
            mock_content=json.dumps(mock_obj, ensure_ascii=False),
        )
        return result
