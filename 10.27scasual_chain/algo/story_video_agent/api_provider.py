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
import socket
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
  STORY_PLANNER_TOKEN_PARAM / STORY_VLM_TOKEN_PARAM
                                        per-role override of token field name
  STORY_PLANNER_MAX_COMPLETION_TOKENS / STORY_VLM_MAX_COMPLETION_TOKENS
                                        per-role output budget (min'd with global)
  STORY_PLANNER_SEND_THINKING / STORY_VLM_SEND_THINKING=1
                                        only then may send enable_thinking/thinking_budget
                                        (Paratera public docs do NOT list these — opt-in)
  STORY_PLANNER_ENABLE_THINKING / STORY_VLM_ENABLE_THINKING
  STORY_PLANNER_THINKING_BUDGET / STORY_VLM_THINKING_BUDGET
  STORY_VLM_REQUEST_PROFILE / STORY_PLANNER_REQUEST_PROFILE
                                        default | video_rsi
                                        video_rsi mirrors Video-RSI PinnedProvider.chat:
                                        temperature (role default 0 for VLM), max_tokens,
                                        thinking={{"type":"disabled"}}, stream=false
                                        Mutually exclusive with enable_thinking/thinking_budget.
                                        Paratera docs do NOT document the thinking object —
                                        profile is offline/Mock-safe; do not assume vendor support.
  STORY_VLM_TEMPERATURE / STORY_PLANNER_TEMPERATURE
  STORY_VLM_THINKING_OBJECT_DISABLED=1   opt-in alone (without full video_rsi profile)

provider modes: mock | real | degraded | cache
HTTP attempts (success+failure+retry) count toward MAX_CALLS; cache hits do not.
If reported completion_tokens exceed configured output budget, later real calls block.
Logs never print API keys, image base64, or reasoning_content text.
""".strip()

# Video-RSI 官方参考（solver_full_workspace/engine/services.py PinnedProvider.chat）
VIDEO_RSI_COMPAT_NOTE = (
    "Video-RSI PinnedProvider.chat sends temperature, max_tokens, "
    "thinking={'type':'disabled'}, stream=false. Official max_tokens=8192 must NOT be "
    "copied into this project; local HTTP/token/cost caps still apply."
)

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
    # 供应商差异：只发其中一个字段，禁止同时发送 max_tokens + max_completion_tokens
    token_param: str = "max_tokens"  # max_tokens | max_completion_tokens | none
    # 角色级输出预算；None → 使用 ApiProvider 全局 max_completion_tokens
    max_completion_tokens: Optional[int] = None
    # Thinking：仅当 send_thinking_params=True 时写入请求体（默认不发）
    send_thinking_params: bool = False
    enable_thinking: Optional[bool] = None
    thinking_budget: Optional[int] = None
    # default | video_rsi（按角色；默认 default 不影响 Planner）
    request_profile: str = "default"
    # 角色默认温度；None → 调用方 chat(temperature=...) 决定
    default_temperature: Optional[float] = None
    # Video-RSI: thinking={"type":"disabled"}；与 enable_thinking/thinking_budget 互斥
    thinking_object_disabled: bool = False
    # 始终建议显式 stream=false（Video-RSI 与 Paratera 示例均如此）
    stream: bool = False

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
            "max_completion_tokens": self.max_completion_tokens,
            "send_thinking_params": self.send_thinking_params,
            "enable_thinking": self.enable_thinking,
            "thinking_budget": self.thinking_budget,
            "request_profile": self.request_profile,
            "default_temperature": self.default_temperature,
            "thinking_object_disabled": self.thinking_object_disabled,
            "stream": self.stream,
        }

    def cache_fingerprint(self) -> str:
        return (
            f"{self.role}|{self.base_url}|{self.model}|{self.token_param}|"
            f"{self.max_completion_tokens}|{self.send_thinking_params}|"
            f"{self.enable_thinking}|{self.thinking_budget}|"
            f"{self.request_profile}|{self.default_temperature}|"
            f"{self.thinking_object_disabled}|{self.stream}"
        )


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
    # 脱敏审计（不含 reasoning 原文 / key）
    request_token_param: str = ""
    request_token_limit: Optional[int] = None
    request_thinking_sent: bool = False
    finish_reason: str = ""
    reasoning_tokens: Optional[int] = None
    visible_output_chars: int = 0
    output_budget_exceeded: bool = False

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
            "output_budget_exceeded_count": sum(
                1 for c in self.calls if c.output_budget_exceeded
            ),
            "by_role": {
                role: {
                    "http_attempts": sum(1 for c in http_attempts if c.role == role),
                    "tokens": sum(c.total_tokens for c in real_ok if c.role == role),
                    "est_cost_usd": round(
                        sum(c.est_cost_usd for c in real_ok if c.role == role), 6
                    ),
                    "output_budget_exceeded": any(
                        c.output_budget_exceeded for c in self.calls if c.role == role
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


def _resolve_token_param(*role_env_names: str) -> str:
    raw = (
        _env(*role_env_names, "STORY_API_TOKEN_PARAM", default="max_tokens") or "max_tokens"
    ).strip()
    if raw in ("max_tokens", "max_completion_tokens", "none"):
        return raw
    return "max_tokens"


def _parse_optional_bool(raw: str) -> Optional[bool]:
    v = (raw or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return None


def _parse_optional_int(raw: str) -> Optional[int]:
    v = (raw or "").strip()
    if not v:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _role_prefix(role: str) -> str:
    return "STORY_PLANNER" if role == "planner" else "STORY_VLM"


def _role_thinking_from_env(role: str) -> Tuple[bool, Optional[bool], Optional[int]]:
    """返回 (send_thinking_params, enable_thinking, thinking_budget)。

    Paratera 公开 API 示例仅展示 max_tokens，未列出 enable_thinking / thinking_budget；
    默认不发送。仅当 STORY_{ROLE}_SEND_THINKING=1 时才附加（调用方自担兼容风险）。
    """
    prefix = _role_prefix(role)
    send = (_env(f"{prefix}_SEND_THINKING") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    enable = _parse_optional_bool(_env(f"{prefix}_ENABLE_THINKING"))
    budget = _parse_optional_int(_env(f"{prefix}_THINKING_BUDGET"))
    return send, enable, budget


def _role_request_profile_from_env(role: str) -> str:
    prefix = _role_prefix(role)
    raw = (_env(f"{prefix}_REQUEST_PROFILE", default="default") or "default").strip().lower()
    if raw in ("default", "video_rsi"):
        return raw
    return "default"


def _role_temperature_from_env(role: str) -> Optional[float]:
    prefix = _role_prefix(role)
    raw = (_env(f"{prefix}_TEMPERATURE") or "").strip()
    if not raw:
        # VLM 默认 0（对齐 Video-RSI / 可配置）；Planner 不设则沿用 chat() 默认 0.1
        if role == "vision":
            return 0.0
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _role_thinking_object_disabled_from_env(role: str) -> bool:
    """Video-RSI thinking={type:disabled} 显式 opt-in，或 video_rsi profile 自动开启。"""
    prefix = _role_prefix(role)
    if _role_request_profile_from_env(role) == "video_rsi":
        return True
    return (_env(f"{prefix}_THINKING_OBJECT_DISABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def frame_time_binding_text(binding: Optional[Dict[str, Any]], frame_id: str) -> str:
    """程序绑定的帧时间说明；模型不得自行创造媒体时间。"""
    b = binding if isinstance(binding, dict) else {}
    fid = str(b.get("frame_id") or frame_id)
    lines = [f"frame_id={fid}"]
    actual = b.get("actual_media_sec")
    requested = b.get("requested_media_sec")
    pts_status = str(b.get("pts_status") or "")
    if actual is not None and pts_status != "requested_only":
        try:
            lines.append(f"actual_media_sec={float(actual):.3f}")
            lines.append("media_time_status=actual_pts")
        except (TypeError, ValueError):
            lines.append("media_time_status=requested_only")
            if requested is not None:
                lines.append(f"requested_media_sec={float(requested):.3f}")
    else:
        lines.append("media_time_status=requested_only")
        if requested is not None:
            try:
                lines.append(f"requested_media_sec={float(requested):.3f}")
            except (TypeError, ValueError):
                pass
        lines.append("note=PTS unavailable; do not invent media time")
    # Video-RSI 使用 timestamp_seconds=；此处额外给出绑定语义，禁止模型编造
    return "\n".join(lines)


def redact_request_body_for_diff(body: Dict[str, Any]) -> Dict[str, Any]:
    """脱敏请求体用于差异报告：去掉 base64 / key，保留结构。"""
    import copy

    out = copy.deepcopy(body)

    def _walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            if "url" in obj and isinstance(obj["url"], str) and obj["url"].startswith(
                "data:image"
            ):
                obj["url"] = "data:image/jpeg;base64,[REDACTED_FRAME]"
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(x) for x in obj]
        if isinstance(obj, str) and obj.startswith("data:image"):
            return "data:image/jpeg;base64,[REDACTED_FRAME]"
        return obj

    return _walk(out)


def extract_usage_audit(payload: Dict[str, Any], *, content: str) -> Dict[str, Any]:
    """从响应提取脱敏审计字段；缺失字段保持 None，不伪造。"""
    usage = payload.get("usage") if isinstance(payload, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get("completion_tokens_details")
    reasoning_tokens: Optional[int] = None
    if isinstance(details, dict) and details.get("reasoning_tokens") is not None:
        try:
            reasoning_tokens = int(details.get("reasoning_tokens"))
        except (TypeError, ValueError):
            reasoning_tokens = None
    finish_reason = ""
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if isinstance(choices, list) and choices:
        c0 = choices[0] if isinstance(choices[0], dict) else {}
        finish_reason = str(c0.get("finish_reason") or "")
        # 明确不读取 / 不保存 message.reasoning_content 原文
    return {
        "finish_reason": finish_reason,
        "reasoning_tokens": reasoning_tokens,
        "visible_output_chars": len(content or ""),
        "usage_keys_present": sorted(usage.keys()),
        "has_completion_tokens_details": isinstance(details, dict),
        "reasoning_content_present": bool(
            isinstance(choices, list)
            and choices
            and isinstance(choices[0], dict)
            and isinstance(choices[0].get("message"), dict)
            and (choices[0]["message"].get("reasoning_content") not in (None, ""))
        ),
        # 仅布尔：是否存在 reasoning_content；从不回传文本
    }


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
    base = _env("STORY_LLM_BASE_URL", "OPENAI_BASE_URL").rstrip("/")
    key = _env("STORY_LLM_API_KEY", "OPENAI_API_KEY")
    planner_model = _env("STORY_LLM_MODEL", "OPENAI_MODEL")
    vbase = _env("STORY_VLM_BASE_URL", default=base).rstrip("/")
    vkey = _env("STORY_VLM_API_KEY", default=key)
    vmodel = _env("STORY_VLM_MODEL", default=planner_model)
    planner_tok = _resolve_token_param("STORY_PLANNER_TOKEN_PARAM")
    vision_tok = _resolve_token_param("STORY_VLM_TOKEN_PARAM")
    planner_max = _parse_optional_int(_env("STORY_PLANNER_MAX_COMPLETION_TOKENS"))
    vision_max = _parse_optional_int(_env("STORY_VLM_MAX_COMPLETION_TOKENS"))
    p_send, p_en, p_bud = _role_thinking_from_env("planner")
    v_send, v_en, v_bud = _role_thinking_from_env("vision")
    p_profile = _role_request_profile_from_env("planner")
    v_profile = _role_request_profile_from_env("vision")
    # video_rsi 官方使用 max_tokens 字段名
    if v_profile == "video_rsi" and not (_env("STORY_VLM_TOKEN_PARAM") or "").strip():
        vision_tok = "max_tokens"
    if p_profile == "video_rsi" and not (_env("STORY_PLANNER_TOKEN_PARAM") or "").strip():
        planner_tok = "max_tokens"
    return {
        "planner": EndpointConfig(
            role="planner",
            base_url=base,
            api_key=key,
            model=planner_model,
            timeout_sec=timeout,
            max_retries=retries,
            rpm=rpm,
            token_param=planner_tok,
            max_completion_tokens=planner_max,
            send_thinking_params=p_send,
            enable_thinking=p_en,
            thinking_budget=p_bud,
            request_profile=p_profile,
            default_temperature=_role_temperature_from_env("planner"),
            thinking_object_disabled=_role_thinking_object_disabled_from_env("planner"),
            stream=False,
        ),
        "vision": EndpointConfig(
            role="vision",
            base_url=vbase,
            api_key=vkey,
            model=vmodel,
            timeout_sec=timeout,
            max_retries=retries,
            rpm=rpm,
            token_param=vision_tok,
            max_completion_tokens=vision_max,
            send_thinking_params=v_send,
            enable_thinking=v_en,
            thinking_budget=v_bud,
            request_profile=v_profile,
            default_temperature=_role_temperature_from_env("vision"),
            thinking_object_disabled=_role_thinking_object_disabled_from_env("vision"),
            stream=False,
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


def _sanitize_error_text(text: str, *, limit: int = 240) -> str:
    """脱敏诊断文本：去掉 Key / Authorization / 图片 base64 / 代理凭证。"""
    import re

    s = str(text or "")
    s = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+", r"\1[REDACTED]", s)
    s = re.sub(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*", "Bearer [REDACTED]", s)
    s = re.sub(r"sk-[A-Za-z0-9_\-]{6,}", "[REDACTED_KEY]", s)
    s = re.sub(
        r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+",
        "data:image/<redacted_base64>",
        s,
    )
    # user:pass@host in proxy URLs
    s = re.sub(
        r"(://)([^/@:\s]+):([^/@\s]+)@",
        r"\1[REDACTED_USER]:[REDACTED_PASS]@",
        s,
    )
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def _network_error_category(reason: Any) -> str:
    """将 URLError.reason / 连接类异常归为 dns|tls|proxy|timeout|connection|urlerror。"""
    if isinstance(reason, TimeoutError):
        return "timeout"
    text = str(reason or "").lower()
    rtype = type(reason).__name__.lower() if reason is not None else ""
    if (
        isinstance(reason, socket.gaierror)
        or "name resolution" in text
        or "nodename nor servname" in text
        or "name or service not known" in text
        or rtype == "gaierror"
    ):
        return "dns"
    if (
        "tunnel connection failed" in text
        or "proxy error" in text
        or "proxy connection" in text
        or "407" in text
        or ("proxy" in text and ("403" in text or "failed" in text))
    ):
        return "proxy"
    if (
        "ssl" in text
        or "tls" in text
        or "certificate" in text
        or "CERTIFICATE" in str(reason or "")
        or "SSL" in type(reason).__name__
    ):
        return "tls"
    if "timed out" in text or "timeout" in text or rtype.endswith("timeout"):
        return "timeout"
    if (
        isinstance(reason, ConnectionError)
        or "connection refused" in text
        or "connection reset" in text
        or "network is unreachable" in text
    ):
        return "connection"
    return "urlerror"


def _classify_urlerror(exc: urllib.error.URLError) -> Tuple[bool, int, str]:
    reason = getattr(exc, "reason", None)
    category = _network_error_category(reason)
    reason_type = type(reason).__name__ if reason is not None else "None"
    detail = _sanitize_error_text(str(reason) if reason is not None else str(exc))
    msg = (
        f"URLError category={category} reason_type={reason_type} detail={detail}"
    )
    return True, 0, msg


def _failure_status_from_http(http_status: int, message: str, *, retryable: bool) -> str:
    msg = (message or "").lower()
    # Prefer structured network categories from _classify_urlerror
    for cat in ("dns", "proxy", "tls", "timeout", "connection"):
        if f"category={cat}" in msg:
            return f"network_{cat}"
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
    if "urlerror" in msg and "category=" in msg:
        return "network_urlerror"
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
        return exc.retryable, exc.http_status, _sanitize_error_text(str(exc))
    if isinstance(exc, urllib.error.HTTPError):
        code = int(exc.code)
        return code in _RETRYABLE_HTTP, code, f"HTTP {code}"
    if isinstance(exc, urllib.error.URLError):
        return _classify_urlerror(exc)
    if isinstance(exc, TimeoutError):
        detail = _sanitize_error_text(str(exc) or "TimeoutError")
        return True, 0, f"TimeoutError category=timeout detail={detail}"
    if isinstance(exc, ConnectionError):
        cat = _network_error_category(exc)
        detail = _sanitize_error_text(str(exc))
        return True, 0, f"ConnectionError category={cat} detail={detail}"
    msg = _sanitize_error_text(str(exc))
    if "timed out" in msg.lower() or "timeout" in msg.lower():
        return True, 0, msg[:200]
    return False, 0, msg[:200]


def _safe_log_error(role: str, message: str) -> None:
    scrubbed = _sanitize_error_text(message, limit=300)
    logger.warning("api role=%s error=%s", role, scrubbed)


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
        # 任一角色实测 completion_tokens 超过配置输出预算后阻断后续真实请求
        self._output_budget_exceeded = False
        self._output_budget_exceeded_roles: List[str] = []

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
            "output_budget_exceeded": self._output_budget_exceeded,
            "output_budget_exceeded_roles": list(self._output_budget_exceeded_roles),
            "cost_disclaimer": self.cost_disclaimer,
            "notes": self.notes,
            "usage": self.stats.summary(),
        }

    def effective_output_token_limit(self, cfg: EndpointConfig) -> Optional[int]:
        """角色显式上限与全局上限取更严（均未设则 None）。"""
        role_lim = cfg.max_completion_tokens
        glob = self.max_completion_tokens
        if role_lim is None:
            return glob
        if glob is None:
            return role_lim
        return min(int(role_lim), int(glob))

    def _check_caps(self) -> None:
        if self._output_budget_exceeded:
            roles = ",".join(self._output_budget_exceeded_roles) or "?"
            raise ApiCallError(
                f"output token budget previously exceeded for role(s)={roles}; "
                "blocking further real HTTP (reported usage not altered)",
                retryable=False,
                failure_status="output_budget_exceeded",
            )
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

    def build_chat_request_body(
        self,
        cfg: EndpointConfig,
        *,
        messages: Sequence[Dict[str, Any]],
        temperature: float,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """构造 chat/completions 请求体 + 脱敏审计元数据（无 messages 内容/无 key）。"""
        # Video-RSI 风格与 enable_thinking/thinking_budget 互斥
        flat_thinking = bool(
            cfg.send_thinking_params
            and (cfg.enable_thinking is not None or cfg.thinking_budget is not None)
        )
        if cfg.thinking_object_disabled and flat_thinking:
            raise ApiConfigError(
                f"role={cfg.role}: thinking={{type:disabled}} is mutually exclusive with "
                "enable_thinking/thinking_budget; refuse both formats"
            )

        body: Dict[str, Any] = {
            "model": cfg.model,
            "temperature": float(temperature),
            "messages": list(messages),
            # 显式 stream=false（Video-RSI 与 Paratera 示例一致）；禁止默认省略导致供应商流式差异
            "stream": False if not cfg.stream else True,
        }

        limit = self.effective_output_token_limit(cfg)
        param = (cfg.token_param or "max_tokens").strip()
        if cfg.request_profile == "video_rsi":
            # 官方固定使用 max_tokens 字段名；额度仍受本项目 cap，禁止照搬 8192
            param = "max_tokens"
        token_field_sent: Optional[str] = None
        if limit is not None:
            if param == "max_tokens":
                body["max_tokens"] = int(limit)
                token_field_sent = "max_tokens"
            elif param == "max_completion_tokens":
                body["max_completion_tokens"] = int(limit)
                token_field_sent = "max_completion_tokens"
            # param == "none" → 不附加长度字段
        # 禁止同时携带两个长度字段
        if "max_tokens" in body and "max_completion_tokens" in body:
            raise ApiConfigError("refusing to send both max_tokens and max_completion_tokens")

        thinking_flat_sent = False
        thinking_object_sent = False
        if cfg.thinking_object_disabled:
            body["thinking"] = {"type": "disabled"}
            thinking_object_sent = True
        elif cfg.send_thinking_params:
            if cfg.enable_thinking is not None:
                body["enable_thinking"] = bool(cfg.enable_thinking)
                thinking_flat_sent = True
            if cfg.thinking_budget is not None:
                body["thinking_budget"] = int(cfg.thinking_budget)
                thinking_flat_sent = True

        audit = {
            "role": cfg.role,
            "model": cfg.model,
            "request_profile": cfg.request_profile,
            "token_param_configured": cfg.token_param,
            "token_param_sent": token_field_sent,
            "token_limit_sent": int(limit) if limit is not None and token_field_sent else None,
            "temperature_sent": body.get("temperature"),
            "stream_sent": body.get("stream"),
            "thinking_params_sent": thinking_flat_sent,
            "thinking_object_disabled_sent": thinking_object_sent,
            "enable_thinking_sent": body.get("enable_thinking") if thinking_flat_sent else None,
            "thinking_budget_sent": body.get("thinking_budget") if thinking_flat_sent else None,
            "sends_both_token_params": False,
            "sends_both_thinking_formats": False,
            "message_count": len(messages),
            "video_rsi_compat_note": VIDEO_RSI_COMPAT_NOTE,
            "paratera_thinking_object_documented": False,
            # 不记录 messages / Authorization
        }
        return body, audit

    def chat(
        self,
        *,
        role: str,
        messages: Sequence[Dict[str, Any]],
        temperature: Optional[float] = None,
        cache_key: Optional[str] = None,
        mock_content: Optional[str] = None,
        allow_degraded_fallback: bool = False,
    ) -> Dict[str, Any]:
        cfg = self.configs[role]
        if temperature is None:
            if cfg.default_temperature is not None:
                temperature = float(cfg.default_temperature)
            else:
                temperature = 0.1
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
                body, req_audit = self.build_chat_request_body(
                    cfg, messages=messages, temperature=temperature
                )
                payload = self._post_chat(cfg, body=body)
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
                usage_audit = extract_usage_audit(payload, content=content)
                limit = self.effective_output_token_limit(cfg)
                exceeded = bool(limit is not None and ct > int(limit))
                # Reasoning models often report completion_tokens >> max_tokens while still
                # returning usable visible content (finish_reason=stop). Hard-block only when
                # truncated/empty, or when STORY_API_HARD_BLOCK_ON_OUTPUT_BUDGET=1.
                hard_env = (_env("STORY_API_HARD_BLOCK_ON_OUTPUT_BUDGET") or "").strip().lower()
                hard_block = hard_env in ("1", "true", "yes", "on")
                finish_reason = str(usage_audit.get("finish_reason") or "")
                visible_chars = int(usage_audit.get("visible_output_chars") or len(content))
                truncated_empty = finish_reason == "length" and visible_chars < 8
                if exceeded and (hard_block or truncated_empty):
                    self._output_budget_exceeded = True
                    if role not in self._output_budget_exceeded_roles:
                        self._output_budget_exceeded_roles.append(role)
                result = {
                    "content": content,
                    "usage": {
                        "prompt_tokens": pt,
                        "completion_tokens": ct,
                        "total_tokens": tt,
                        # 透传 details 键是否存在；不改写供应商数值
                        "completion_tokens_details": usage.get("completion_tokens_details"),
                    },
                    "model": cfg.model,
                    "provider": "openai_compatible",
                    "provider_mode": "real",
                    "cached": False,
                    "est_cost_usd": cost,
                    "cost_disclaimer": COST_DISCLAIMER,
                    "raw_response_excerpt": content[:2000],
                    "http_attempt_index": attempt,
                    "request_audit": req_audit,
                    "response_audit": {
                        **usage_audit,
                        "completion_tokens_reported": ct,
                        "output_token_limit": limit,
                        "output_budget_exceeded": exceeded,
                    },
                    "finish_reason": usage_audit.get("finish_reason") or "",
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
                        request_token_param=str(req_audit.get("token_param_sent") or ""),
                        request_token_limit=req_audit.get("token_limit_sent"),
                        request_thinking_sent=bool(req_audit.get("thinking_params_sent")),
                        finish_reason=str(usage_audit.get("finish_reason") or ""),
                        reasoning_tokens=usage_audit.get("reasoning_tokens"),
                        visible_output_chars=int(
                            usage_audit.get("visible_output_chars") or 0
                        ),
                        output_budget_exceeded=exceeded,
                        failure_status="output_budget_exceeded" if exceeded else "",
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
        body: Dict[str, Any],
    ) -> Dict[str, Any]:
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
        frame_bindings: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """多模态观察请求。

        在每张 JPEG 前写入程序绑定的 frame_id 与媒体时间（actual_media_sec 或
        requested_only），对齐 Video-RSI「先文本时间戳再 image_url」结构；模型不得编造时间。
        """
        cfg = self.configs["vision"]
        bindings = list(frame_bindings or [])
        content: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    prompt
                    + " Use only program-provided frame_id / media_time fields; "
                    "never invent media timestamps."
                ),
            }
        ]
        digest = hashlib.sha1()
        digest.update(cfg.cache_fingerprint().encode("utf-8"))
        digest.update(prompt.encode("utf-8"))
        for i, (path, fid) in enumerate(zip(frame_paths, frame_ids)):
            binding = bindings[i] if i < len(bindings) else {"frame_id": fid}
            bind_text = frame_time_binding_text(binding, str(fid))
            content.append({"type": "text", "text": bind_text})
            p = Path(path)
            digest.update(fid.encode("utf-8"))
            digest.update(bind_text.encode("utf-8"))
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
            temperature=cfg.default_temperature,
            cache_key=f"vision:{digest.hexdigest()[:28]}",
            mock_content=json.dumps(mock_obj, ensure_ascii=False),
            allow_degraded_fallback=True,
        )
