"""远程 OpenAI-compatible LLM/VLM Provider（Phase 2C 可信联调）。

严格区分 mock / real / degraded：
- mock：显式 force_mock 或未启用 API（不计费）
- real：STORY_API_ENABLE=1 且配置完整
- degraded：真实调用失败后的显式降级标记（不得伪装成正常观察）

生产启用后缺密钥/模型 → 显式失败，不静默 mock。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("story_video_agent.api")

INTEGRATION_NOTES = """
Story Video Agent remote API (Phase 2C):
  STORY_API_ENABLE=1                    require real HTTP (missing config => hard fail)
  STORY_LLM_BASE_URL / OPENAI_BASE_URL
  STORY_LLM_API_KEY  / OPENAI_API_KEY
  STORY_LLM_MODEL
  STORY_VLM_BASE_URL / STORY_VLM_API_KEY / STORY_VLM_MODEL
  STORY_LLM_TIMEOUT_SEC / STORY_LLM_MAX_RETRIES / STORY_LLM_RPM
  STORY_API_SMOKE=1                     explicit billed smoke entry only
  STORY_API_MAX_CALLS / STORY_API_MAX_COST_USD  hard caps for smoke/real runs

provider modes: mock | real | degraded
Logs never print API keys or image base64.
""".strip()

_DEFAULT_PRICE = {
    "prompt_per_mtok": float(os.environ.get("STORY_LLM_PRICE_PROMPT", "0.15")),
    "completion_per_mtok": float(os.environ.get("STORY_LLM_PRICE_COMPLETION", "0.60")),
}

# HTTP：4xx（除 408/429）不可重试；5xx/超时/连接错误可重试
_RETRYABLE_HTTP = frozenset({408, 429, 500, 502, 503, 504})


class ApiConfigError(RuntimeError):
    """生产模式配置缺失。"""


class ApiCallError(RuntimeError):
    """真实 API 调用失败（带是否可重试标记）。"""

    def __init__(self, message: str, *, retryable: bool = False, http_status: int = 0) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.http_status = http_status


@dataclass
class EndpointConfig:
    role: str
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

    def cache_fingerprint(self) -> str:
        return f"{self.role}|{self.base_url}|{self.model}"


@dataclass
class ApiCallRecord:
    role: str
    model: str
    ok: bool
    mode: str  # mock | real | degraded | cache
    elapsed_sec: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    est_cost_usd: float = 0.0
    cached: bool = False
    error: str = ""
    http_status: int = 0
    retryable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ApiUsageStats:
    calls: List[ApiCallRecord] = field(default_factory=list)

    def add(self, row: ApiCallRecord) -> None:
        self.calls.append(row)

    def summary(self) -> Dict[str, Any]:
        real = [c for c in self.calls if c.mode == "real" and not c.cached]
        cached = [c for c in self.calls if c.cached]
        mock = [c for c in self.calls if c.mode == "mock"]
        degraded = [c for c in self.calls if c.mode == "degraded"]
        return {
            "calls": len(self.calls),
            "real_requests": len(real),
            "cached_hits": len(cached),
            "mock_calls": len(mock),
            "degraded_calls": len(degraded),
            "ok": sum(1 for c in self.calls if c.ok),
            "failures": sum(1 for c in self.calls if not c.ok),
            "prompt_tokens": sum(c.prompt_tokens for c in real),
            "completion_tokens": sum(c.completion_tokens for c in real),
            "total_tokens": sum(c.total_tokens for c in real),
            "cached_tokens_reported": sum(c.total_tokens for c in cached),
            "est_cost_usd_real": round(sum(c.est_cost_usd for c in real), 6),
            "est_cost_usd_cached_replay": round(sum(c.est_cost_usd for c in cached), 6),
            "elapsed_sec_real": round(sum(c.elapsed_sec for c in real), 4),
            "by_role": {
                role: {
                    "real_requests": sum(1 for c in real if c.role == role),
                    "tokens": sum(c.total_tokens for c in real if c.role == role),
                    "est_cost_usd": round(
                        sum(c.est_cost_usd for c in real if c.role == role), 6
                    ),
                }
                for role in sorted({c.role for c in self.calls} or ["planner", "vision"])
            },
            "records": [c.to_dict() for c in self.calls[-30:]],
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


def _file_content_hash(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 64)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _encode_image(path: Path) -> str:
    import base64

    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    suffix = path.suffix.lower().lstrip(".") or "jpeg"
    mime = "image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}"
    return f"data:{mime};base64,{b64}"


def _classify_error(exc: BaseException) -> Tuple[bool, int, str]:
    if isinstance(exc, ApiCallError):
        return exc.retryable, exc.http_status, str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        code = int(exc.code)
        return code in _RETRYABLE_HTTP, code, f"HTTP {code}"
    if isinstance(exc, (TimeoutError, urllib.error.URLError, ConnectionError)):
        return True, 0, type(exc).__name__
    msg = str(exc)
    if "timed out" in msg.lower() or "timeout" in msg.lower():
        return True, 0, msg[:200]
    return False, 0, msg[:200]


def _safe_log_error(role: str, message: str) -> None:
    # 绝不记录 Authorization / base64
    scrubbed = message
    for token in ("Bearer ", "data:image"):
        if token in scrubbed:
            scrubbed = scrubbed.split(token, 1)[0] + token + "<redacted>"
    logger.warning("api role=%s error=%s", role, scrubbed[:300])


class ApiProvider:
    def __init__(
        self,
        *,
        force_mock: bool = False,
        require_real: bool = False,
        configs: Optional[Dict[str, EndpointConfig]] = None,
        max_calls: Optional[int] = None,
        max_cost_usd: Optional[float] = None,
    ) -> None:
        self.configs = configs or load_endpoint_configs()
        self.require_real = bool(require_real) or api_enabled()
        self.force_mock = bool(force_mock)
        if self.force_mock and self.require_real and api_enabled():
            # 显式 force_mock 优先用于单测；生产 smoke 不应同时 force_mock
            self.require_real = False
        if self.require_real and not self.force_mock:
            missing = [
                role
                for role, cfg in self.configs.items()
                if not cfg.configured()
            ]
            if missing:
                raise ApiConfigError(
                    f"STORY_API_ENABLE/require_real set but endpoints not configured: {missing}. "
                    "Set BASE_URL, API_KEY, MODEL. Refusing silent mock."
                )
        self.stats = ApiUsageStats()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._limiters = {role: _RateLimiter(cfg.rpm) for role, cfg in self.configs.items()}
        self.notes = INTEGRATION_NOTES
        self.max_calls = max_calls
        if self.max_calls is None:
            raw = _env("STORY_API_MAX_CALLS", default="")
            self.max_calls = int(raw) if raw else None
        self.max_cost_usd = max_cost_usd
        if self.max_cost_usd is None:
            raw = _env("STORY_API_MAX_COST_USD", default="")
            self.max_cost_usd = float(raw) if raw else None
        self._real_calls = 0

    def status(self) -> Dict[str, Any]:
        mode = "mock" if self.force_mock or not self.require_real else "real"
        return {
            "mode": mode,
            "api_enabled": api_enabled(),
            "require_real": self.require_real,
            "force_mock": self.force_mock,
            "planner": self.configs["planner"].to_dict(),
            "vision": self.configs["vision"].to_dict(),
            "planner_ready": self.configs["planner"].configured() and self.require_real and not self.force_mock,
            "vision_ready": self.configs["vision"].configured() and self.require_real and not self.force_mock,
            "max_calls": self.max_calls,
            "max_cost_usd": self.max_cost_usd,
            "notes": self.notes,
            "usage": self.stats.summary(),
        }

    def _check_caps(self) -> None:
        if self.max_calls is not None and self._real_calls >= self.max_calls:
            raise ApiCallError(
                f"API max_calls={self.max_calls} exhausted",
                retryable=False,
            )
        if self.max_cost_usd is not None:
            spent = self.stats.summary()["est_cost_usd_real"]
            if spent >= self.max_cost_usd:
                raise ApiCallError(
                    f"API max_cost_usd={self.max_cost_usd} reached (spent={spent})",
                    retryable=False,
                )

    def chat(
        self,
        *,
        role: str,
        messages: Sequence[Dict[str, Any]],
        temperature: float = 0.1,
        cache_key: Optional[str] = None,
        mock_content: Optional[str] = None,
        allow_degraded_fallback: bool = False,
    ) -> Dict[str, Any]:
        cfg = self.configs[role]
        if cache_key and cache_key in self._cache:
            cached = dict(self._cache[cache_key])
            cached["cached"] = True
            cached["provider_mode"] = "cache"
            usage = cached.get("usage") or {}
            self.stats.add(
                ApiCallRecord(
                    role=role,
                    model=str(cached.get("model") or cfg.model or "mock"),
                    ok=True,
                    mode="cache",
                    elapsed_sec=0.0,
                    cached=True,
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                    total_tokens=int(usage.get("total_tokens") or 0),
                    est_cost_usd=float(cached.get("est_cost_usd") or 0.0),
                )
            )
            return cached

        if self.force_mock or not self.require_real:
            content = mock_content if mock_content is not None else '{"ok": true, "mock": true}'
            result = {
                "content": content,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "model": "mock",
                "provider": "mock",
                "provider_mode": "mock",
                "cached": False,
                "est_cost_usd": 0.0,
            }
            self.stats.add(
                ApiCallRecord(
                    role=role, model="mock", ok=True, mode="mock", elapsed_sec=0.0
                )
            )
            if cache_key:
                self._cache[cache_key] = dict(result)
            return result

        if not cfg.configured():
            raise ApiConfigError(f"endpoint {role} not configured for real mode")

        last_err = ""
        http_status = 0
        retryable = False
        t0 = time.perf_counter()
        for attempt in range(cfg.max_retries + 1):
            try:
                self._check_caps()
                self._limiters[role].wait()
                payload = self._post_chat(cfg, messages=messages, temperature=temperature)
                self._real_calls += 1
                elapsed = time.perf_counter() - t0
                usage = payload.get("usage") or {}
                pt = int(usage.get("prompt_tokens") or 0)
                ct = int(usage.get("completion_tokens") or 0)
                tt = int(usage.get("total_tokens") or (pt + ct))
                choices = payload.get("choices") or []
                if not choices:
                    raise ApiCallError("empty choices", retryable=True)
                content = str((choices[0].get("message") or {}).get("content") or "")
                cost = _estimate_cost(pt, ct)
                result = {
                    "content": content,
                    "usage": {
                        "prompt_tokens": pt,
                        "completion_tokens": ct,
                        "total_tokens": tt,
                    },
                    "model": cfg.model,
                    "provider": "openai_compatible",
                    "provider_mode": "real",
                    "cached": False,
                    "est_cost_usd": cost,
                    "raw_response_excerpt": content[:2000],
                }
                self.stats.add(
                    ApiCallRecord(
                        role=role,
                        model=cfg.model,
                        ok=True,
                        mode="real",
                        elapsed_sec=elapsed,
                        prompt_tokens=pt,
                        completion_tokens=ct,
                        total_tokens=tt,
                        est_cost_usd=cost,
                        http_status=200,
                    )
                )
                if cache_key:
                    self._cache[cache_key] = dict(result)
                return result
            except Exception as exc:  # noqa: BLE001
                retryable, http_status, last_err = _classify_error(exc)
                _safe_log_error(role, last_err)
                if (not retryable) or attempt >= cfg.max_retries:
                    break
                time.sleep(0.4 * (2**attempt))

        elapsed = time.perf_counter() - t0
        self.stats.add(
            ApiCallRecord(
                role=role,
                model=cfg.model,
                ok=False,
                mode="degraded",
                elapsed_sec=elapsed,
                error=last_err,
                http_status=http_status,
                retryable=retryable,
            )
        )
        if not allow_degraded_fallback:
            raise ApiCallError(last_err or "api failed", retryable=retryable, http_status=http_status)
        return {
            "content": "",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "model": cfg.model,
            "provider": "degraded",
            "provider_mode": "degraded",
            "cached": False,
            "error": last_err,
            "est_cost_usd": 0.0,
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
            # 不记录可能含密钥的响应头
            raise ApiCallError(
                f"HTTP {exc.code}: {detail[:200]}",
                retryable=exc.code in _RETRYABLE_HTTP,
                http_status=int(exc.code),
            ) from exc

    def plan_decision(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        mock_decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        cfg = self.configs["planner"]
        key_src = f"{cfg.cache_fingerprint()}|{system_prompt}|{user_prompt}"
        key = "plan:" + hashlib.sha1(key_src.encode("utf-8")).hexdigest()[:28]
        return self.chat(
            role="planner",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            cache_key=key,
            mock_content=json.dumps(mock_decision, ensure_ascii=False),
            allow_degraded_fallback=False,
        )

    def vision_json(
        self,
        *,
        prompt: str,
        frame_paths: Sequence[Path],
        frame_ids: Sequence[str],
        mock_obj: Dict[str, Any],
    ) -> Dict[str, Any]:
        cfg = self.configs["vision"]
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        digest = hashlib.sha1()
        digest.update(cfg.cache_fingerprint().encode("utf-8"))
        digest.update(prompt.encode("utf-8"))
        for path, fid in zip(frame_paths, frame_ids):
            content.append({"type": "text", "text": f"frame_id={fid}"})
            p = Path(path)
            digest.update(fid.encode("utf-8"))
            if p.is_file():
                digest.update(_file_content_hash(p).encode("utf-8"))
                content.append(
                    {"type": "image_url", "image_url": {"url": _encode_image(p)}}
                )
        return self.chat(
            role="vision",
            messages=[
                {"role": "system", "content": "Reply with strict JSON only."},
                {"role": "user", "content": content},
            ],
            cache_key=f"vision:{digest.hexdigest()[:28]}",
            mock_content=json.dumps(mock_obj, ensure_ascii=False),
            allow_degraded_fallback=True,  # 视觉层返回 degraded，由上层拒绝 observed
        )
