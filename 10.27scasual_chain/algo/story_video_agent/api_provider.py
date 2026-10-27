"""远程 OpenAI-compatible LLM/VLM Provider（Phase 2C.1 联调准备）。

严格区分 mock / real / degraded / cache：
- mock：显式 force_mock 或未启用 API（不计费）
- real：STORY_API_ENABLE=1 且配置完整；每次真实 HTTP 尝试（成功/失败/重试）计入限额
- cache：缓存命中单独统计，不计入 HTTP 限额
- degraded：真实调用失败后的显式降级（不得伪装成正常观察）

生产启用后缺密钥/模型 → 显式失败，不静默 mock。
费用字段均为本地估算，不是账单硬上限。
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

COST_DISCLAIMER = (
    "est_cost_usd is a local estimate from configured unit prices "
    "(STORY_LLM_PRICE_*); it is NOT a billing guarantee or absolute invoice cap."
)

INTEGRATION_NOTES = """
Story Video Agent remote API (Phase 2C.1):
  STORY_API_ENABLE=1                    require real HTTP (missing config => hard fail)
  STORY_LLM_BASE_URL / OPENAI_BASE_URL
  STORY_LLM_API_KEY  / OPENAI_API_KEY
  STORY_LLM_MODEL
  STORY_VLM_BASE_URL / STORY_VLM_API_KEY / STORY_VLM_MODEL
  STORY_LLM_TIMEOUT_SEC / STORY_LLM_MAX_RETRIES / STORY_LLM_RPM
  STORY_API_SMOKE=1                     explicit billed smoke entry only
  STORY_API_MAX_CALLS                   cap on real HTTP attempts (ok/fail/retry)
  STORY_API_MAX_COST_USD                soft estimate guard (not invoice hard limit)
  STORY_API_MAX_COMPLETION_TOKENS       per-request output token cap (if set)
  STORY_API_TOKEN_PARAM                 max_tokens | max_completion_tokens | none
                                        (default max_tokens; never send both)

provider modes: mock | real | degraded | cache
HTTP attempts (success+failure+retry) count toward MAX_CALLS; cache hits do not.
Logs never print API keys or image base64.
""".strip()

_DEFAULT_PRICE = {
    "prompt_per_mtok": float(os.environ.get("STORY_LLM_PRICE_PROMPT", "0.15")),
    "completion_per_mtok": float(os.environ.get("STORY_LLM_PRICE_COMPLETION", "0.60")),
}

_RETRYABLE_HTTP = frozenset({408, 429, 500, 502, 503, 504})


class ApiConfigError(RuntimeError):
    """生产模式配置缺失。"""


class ApiCallError(RuntimeError):
    """真实 API 调用失败（带是否可重试标记）。"""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        http_status: int = 0,
        failure_status: str = "",
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.http_status = http_status
        self.failure_status = failure_status or _failure_status_from_http(
            http_status, message, retryable=retryable
        )


@dataclass
class EndpointConfig:
    role: str
    base_url: str
    api_key: str
    model: str
    timeout_sec: float = 60.0
    max_retries: int = 2
    rpm: float = 30.0
    # 供应商差异：只发其中一个字段，避免同时发送
    token_param: str = "max_tokens"  # max_tokens | max_completion_tokens | none

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
            "token_param": self.token_param,
        }

    def cache_fingerprint(self) -> str:
        return f"{self.role}|{self.base_url}|{self.model}|{self.token_param}"


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
    http_attempt: bool = False
    attempt_index: int = 0
    failure_status: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ApiUsageStats:
    calls: List[ApiCallRecord] = field(default_factory=list)

    def add(self, row: ApiCallRecord) -> None:
        self.calls.append(row)

    def summary(self) -> Dict[str, Any]:
        http_attempts = [c for c in self.calls if c.http_attempt]
        cached = [c for c in self.calls if c.cached or c.mode == "cache"]
        mock = [c for c in self.calls if c.mode == "mock"]
        degraded = [c for c in self.calls if c.mode == "degraded"]
        real_ok = [c for c in http_attempts if c.ok]
        real_fail = [c for c in http_attempts if not c.ok]
        return {
            "calls": len(self.calls),
            "http_attempts": len(http_attempts),
            "real_requests": len(http_attempts),
            "real_ok": len(real_ok),
            "real_failures": len(real_fail),
            "cached_hits": len(cached),
            "mock_calls": len(mock),
            "degraded_calls": len(degraded),
            "ok": sum(1 for c in self.calls if c.ok),
            "failures": sum(1 for c in self.calls if not c.ok),
            "prompt_tokens": sum(c.prompt_tokens for c in real_ok),
            "completion_tokens": sum(c.completion_tokens for c in real_ok),
            "total_tokens": sum(c.total_tokens for c in real_ok),
            "cached_tokens_reported": sum(c.total_tokens for c in cached),
            "est_cost_usd_real": round(sum(c.est_cost_usd for c in real_ok), 6),
            "est_cost_usd_cached_replay": round(sum(c.est_cost_usd for c in cached), 6),
            "cost_disclaimer": COST_DISCLAIMER,
            "elapsed_sec_real": round(sum(c.elapsed_sec for c in http_attempts), 4),
            "by_role": {
                role: {
                    "http_attempts": sum(1 for c in http_attempts if c.role == role),
                    "tokens": sum(c.total_tokens for c in real_ok if c.role == role),
                    "est_cost_usd": round(
                        sum(c.est_cost_usd for c in real_ok if c.role == role), 6
                    ),
                }
                for role in sorted({c.role for c in self.calls} or ["planner", "vision"])
            },
            "records": [c.to_dict() for c in self.calls[-40:]],
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


def _resolve_token_param() -> str:
    raw = (_env("STORY_API_TOKEN_PARAM", default="max_tokens") or "max_tokens").strip()
    if raw in ("max_tokens", "max_completion_tokens", "none"):
        return raw
    return "max_tokens"


def _stricter_int_cap(explicit: Optional[int], env_name: str) -> Optional[int]:
    """代码显式上限与环境变量取更严（更小）；任一缺失则用另一方。"""
    env_raw = _env(env_name, default="")
    env_val: Optional[int] = int(env_raw) if env_raw else None
    if explicit is None:
        return env_val
    if env_val is None:
        return int(explicit)
    return min(int(explicit), int(env_val))


def _stricter_float_cap(explicit: Optional[float], env_name: str) -> Optional[float]:
    env_raw = _env(env_name, default="")
    env_val: Optional[float] = float(env_raw) if env_raw else None
    if explicit is None:
        return env_val
    if env_val is None:
        return float(explicit)
    return min(float(explicit), float(env_val))


def _cap_source_note(
    explicit: Any, env_name: str, effective: Any
) -> Dict[str, Any]:
    env_raw = _env(env_name, default="") or None
    return {
        "env_name": env_name,
        "env_value": env_raw,
        "explicit_value": explicit,
        "effective": effective,
        "policy": "min(explicit, env) when both set",
    }


def resolve_effective_caps(
    *,
    max_calls: Optional[int] = None,
    max_cost_usd: Optional[float] = None,
    max_completion_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """供 dry-check / Phase4A 预检：报告真正生效的限额（不含 API Key）。"""
    eff_calls = _stricter_int_cap(max_calls, "STORY_API_MAX_CALLS")
    eff_cost = _stricter_float_cap(max_cost_usd, "STORY_API_MAX_COST_USD")
    eff_tok = _stricter_int_cap(max_completion_tokens, "STORY_API_MAX_COMPLETION_TOKENS")
    return {
        "max_calls": eff_calls,
        "max_cost_usd": eff_cost,
        "max_completion_tokens": eff_tok,
        "sources": {
            "max_calls": _cap_source_note(max_calls, "STORY_API_MAX_CALLS", eff_calls),
            "max_cost_usd": _cap_source_note(
                max_cost_usd, "STORY_API_MAX_COST_USD", eff_cost
            ),
            "max_completion_tokens": _cap_source_note(
                max_completion_tokens, "STORY_API_MAX_COMPLETION_TOKENS", eff_tok
            ),
        },
        "cost_disclaimer": COST_DISCLAIMER,
        "token_param": _resolve_token_param(),
    }


def load_endpoint_configs() -> Dict[str, EndpointConfig]:
    timeout = float(_env("STORY_LLM_TIMEOUT_SEC", default="60") or 60)
    retries = int(float(_env("STORY_LLM_MAX_RETRIES", default="2") or 2))
    rpm = float(_env("STORY_LLM_RPM", default="30") or 30)
    token_param = _resolve_token_param()
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
            token_param=token_param,
        ),
        "vision": EndpointConfig(
            role="vision",
            base_url=vbase,
            api_key=vkey,
            model=vmodel,
            timeout_sec=timeout,
            max_retries=retries,
            rpm=rpm,
            token_param=token_param,
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


def _failure_status_from_http(http_status: int, message: str, *, retryable: bool) -> str:
    msg = (message or "").lower()
    if http_status == 429 or "429" in msg:
        return "http_429"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if http_status == 408:
        return "timeout"
    if http_status >= 500:
        return "http_5xx"
    if http_status >= 400:
        return f"http_{http_status}"
    if retryable:
        return "transient_error"
    return "api_error"


def failure_status_from_exc(exc: BaseException) -> str:
    if isinstance(exc, ApiCallError) and exc.failure_status:
        return exc.failure_status
    retryable, http_status, message = _classify_error(exc)
    return _failure_status_from_http(http_status, message, retryable=retryable)


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
        max_completion_tokens: Optional[int] = None,
        required_roles: Optional[Sequence[str]] = None,
    ) -> None:
        self.configs = configs or load_endpoint_configs()
        self.require_real = bool(require_real) or api_enabled()
        self.force_mock = bool(force_mock)
        self.required_roles = (
            list(required_roles) if required_roles else list(self.configs.keys())
        )
        if self.force_mock and self.require_real and api_enabled():
            self.require_real = False
        if self.require_real and not self.force_mock:
            missing = [
                role
                for role in self.required_roles
                if role in self.configs and not self.configs[role].configured()
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
        self.cost_disclaimer = COST_DISCLAIMER
        # 显式参数与环境变量取更严上限，避免 Phase4A 默认 12 覆盖 STORY_API_MAX_CALLS=3
        self.max_calls = _stricter_int_cap(max_calls, "STORY_API_MAX_CALLS")
        self.max_cost_usd = _stricter_float_cap(max_cost_usd, "STORY_API_MAX_COST_USD")
        self.max_completion_tokens = _stricter_int_cap(
            max_completion_tokens, "STORY_API_MAX_COMPLETION_TOKENS"
        )
        self.cap_sources = {
            "max_calls": _cap_source_note(max_calls, "STORY_API_MAX_CALLS", self.max_calls),
            "max_cost_usd": _cap_source_note(
                max_cost_usd, "STORY_API_MAX_COST_USD", self.max_cost_usd
            ),
            "max_completion_tokens": _cap_source_note(
                max_completion_tokens,
                "STORY_API_MAX_COMPLETION_TOKENS",
                self.max_completion_tokens,
            ),
        }
        self._http_attempts = 0

    def status(self) -> Dict[str, Any]:
        mode = "mock" if self.force_mock or not self.require_real else "real"
        return {
            "mode": mode,
            "api_enabled": api_enabled(),
            "require_real": self.require_real,
            "force_mock": self.force_mock,
            "required_roles": list(self.required_roles),
            "planner": self.configs["planner"].to_dict(),
            "vision": self.configs["vision"].to_dict(),
            "planner_ready": (
                self.configs["planner"].configured()
                and self.require_real
                and not self.force_mock
                and "planner" in self.required_roles
            ),
            "vision_ready": (
                self.configs["vision"].configured()
                and self.require_real
                and not self.force_mock
                and "vision" in self.required_roles
            ),
            "max_calls": self.max_calls,
            "max_cost_usd": self.max_cost_usd,
            "max_completion_tokens": self.max_completion_tokens,
            "cap_sources": dict(self.cap_sources),
            "token_param": _resolve_token_param(),
            "http_attempts": self._http_attempts,
            "cost_disclaimer": self.cost_disclaimer,
            "notes": self.notes,
            "usage": self.stats.summary(),
        }

    def _check_caps(self) -> None:
        if self.max_calls is not None and self._http_attempts >= self.max_calls:
            raise ApiCallError(
                f"API max_calls={self.max_calls} exhausted "
                f"(http_attempts={self._http_attempts}; cache hits excluded)",
                retryable=False,
                failure_status="budget_exhausted",
            )
        if self.max_cost_usd is not None:
            spent = self.stats.summary()["est_cost_usd_real"]
            if spent >= self.max_cost_usd:
                raise ApiCallError(
                    f"API estimate soft-cap max_cost_usd={self.max_cost_usd} reached "
                    f"(est_spent={spent}). {COST_DISCLAIMER}",
                    retryable=False,
                    failure_status="cost_estimate_cap",
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
                    http_attempt=False,
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
        failure_status = "api_error"
        t0 = time.perf_counter()
        for attempt in range(cfg.max_retries + 1):
            http_started = False
            attempt_t0 = time.perf_counter()
            try:
                self._check_caps()
                self._limiters[role].wait()
                self._http_attempts += 1
                http_started = True
                payload = self._post_chat(cfg, messages=messages, temperature=temperature)
                elapsed = time.perf_counter() - attempt_t0
                usage = payload.get("usage") or {}
                pt = int(usage.get("prompt_tokens") or 0)
                ct = int(usage.get("completion_tokens") or 0)
                tt = int(usage.get("total_tokens") or (pt + ct))
                choices = payload.get("choices") or []
                if not choices:
                    raise ApiCallError(
                        "empty choices",
                        retryable=True,
                        failure_status="empty_response",
                    )
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
                    "cost_disclaimer": COST_DISCLAIMER,
                    "raw_response_excerpt": content[:2000],
                    "http_attempt_index": attempt,
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
                        http_attempt=True,
                        attempt_index=attempt,
                    )
                )
                if cache_key:
                    self._cache[cache_key] = dict(result)
                return result
            except Exception as exc:  # noqa: BLE001
                retryable, http_status, last_err = _classify_error(exc)
                failure_status = failure_status_from_exc(exc)
                _safe_log_error(role, last_err)
                if http_started:
                    self.stats.add(
                        ApiCallRecord(
                            role=role,
                            model=cfg.model,
                            ok=False,
                            mode="real",
                            elapsed_sec=time.perf_counter() - attempt_t0,
                            error=last_err[:300],
                            http_status=http_status,
                            retryable=retryable,
                            http_attempt=True,
                            attempt_index=attempt,
                            failure_status=failure_status,
                        )
                    )
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
                failure_status=failure_status,
                http_attempt=False,
            )
        )
        if not allow_degraded_fallback:
            raise ApiCallError(
                last_err or "api failed",
                retryable=retryable,
                http_status=http_status,
                failure_status=failure_status,
            )
        return {
            "content": "",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "model": cfg.model,
            "provider": "degraded",
            "provider_mode": "degraded",
            "cached": False,
            "error": last_err,
            "failure_status": failure_status,
            "http_status": http_status,
            "est_cost_usd": 0.0,
            "cost_disclaimer": COST_DISCLAIMER,
        }

    def _post_chat(
        self,
        cfg: EndpointConfig,
        *,
        messages: Sequence[Dict[str, Any]],
        temperature: float,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": cfg.model,
            "temperature": temperature,
            "messages": list(messages),
        }
        if self.max_completion_tokens is not None:
            # 按供应商配置只发送一个字段，禁止默认同时发送
            param = (cfg.token_param or "max_tokens").strip()
            if param == "max_tokens":
                body["max_tokens"] = int(self.max_completion_tokens)
            elif param == "max_completion_tokens":
                body["max_completion_tokens"] = int(self.max_completion_tokens)
            # param == "none" → 不附加输出长度字段
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
            allow_degraded_fallback=True,
        )
