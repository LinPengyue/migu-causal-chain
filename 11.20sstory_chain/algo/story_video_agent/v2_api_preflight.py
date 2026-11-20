"""API preflight for Strip-Guided Round 2.1 — verify Planner + Vision before full runs.

Never logs API keys. Non-retryable 400/401/403 fail fast.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.api_provider import (
    COST_DISCLAIMER,
    EndpointConfig,
    load_endpoint_configs,
)

_FATAL_HTTP = frozenset({400, 401, 403})
_INVALID_MODEL_MARKERS = (
    "invalid model name",
    "model not found",
    "team_model_access_denied",
    "team not allowed to access model",
)


class PreflightError(RuntimeError):
    """Raised when planner/vision capability is not proven."""

    def __init__(self, message: str, *, report: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.report = report or {}


def _scrub(text: str, limit: int = 240) -> str:
    t = str(text or "")
    # never echo bearer tokens if somehow present
    if "Bearer " in t:
        t = t.split("Bearer ", 1)[0] + "Bearer ***"
    if "sk-" in t:
        t = t.replace("sk-", "sk-***")
    return t[:limit]


def _classify_http_detail(http: int, detail: str) -> Dict[str, Any]:
    low = (detail or "").lower()
    invalid_model = any(m in low for m in _INVALID_MODEL_MARKERS)
    auth = http in (401, 403) or "authentication" in low or "unauthorized" in low
    return {
        "http_status": http,
        "fatal_non_retryable": http in _FATAL_HTTP,
        "invalid_model": invalid_model,
        "auth_problem": auth,
        "format_or_other_400": http == 400 and not invalid_model and not auth,
        "detail_scrubbed": _scrub(detail),
    }


def _post_chat(
    cfg: EndpointConfig,
    *,
    body: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg.api_key}",
    }
    req = urllib.request.Request(
        f"{cfg.base_url.rstrip('/')}/chat/completions",
        data=data,
        headers=headers,
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=min(60, int(cfg.timeout_sec or 60))) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        return payload, {"ok": True, "http_status": 200, "latency_sec": round(time.time() - t0, 3)}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        meta = _classify_http_detail(int(exc.code), detail)
        meta.update({"ok": False, "latency_sec": round(time.time() - t0, 3)})
        return None, meta
    except Exception as exc:  # noqa: BLE001
        return None, {
            "ok": False,
            "http_status": 0,
            "fatal_non_retryable": False,
            "error": _scrub(str(exc)),
            "latency_sec": round(time.time() - t0, 3),
        }


def _content_of(payload: Optional[Dict[str, Any]]) -> str:
    if not payload:
        return ""
    ch = (payload.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    return str(msg.get("content") or "")


def list_models(cfg: EndpointConfig) -> Dict[str, Any]:
    req = urllib.request.Request(
        f"{cfg.base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {cfg.api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        ids = sorted(m.get("id") for m in (data.get("data") or []) if m.get("id"))
        return {"ok": True, "n_models": len(ids), "model_ids": ids, "http_status": 200}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        meta = _classify_http_detail(int(exc.code), detail)
        meta.update({"ok": False, "n_models": 0, "model_ids": []})
        return meta
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "n_models": 0, "model_ids": [], "error": _scrub(str(exc))}


def _tiny_or_file_b64(image_path: Optional[Path]) -> Tuple[str, str]:
    if image_path and Path(image_path).is_file():
        raw = Path(image_path).read_bytes()
        suffix = Path(image_path).suffix.lower()
        mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
        return base64.b64encode(raw).decode("ascii"), mime
    # 32x32 PNG — many VLMs reject width/height <= 10.
    try:
        import struct
        import zlib

        def _chunk(tag: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + tag
                + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
            )

        w = h = 32
        raw_rows = b"".join(b"\x00" + (b"\x80\x80\x80" * w) for _ in range(h))
        png = (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw_rows, 9))
            + _chunk(b"IEND", b"")
        )
        return base64.b64encode(png).decode("ascii"), "image/png"
    except Exception:  # noqa: BLE001
        # fallback minimal valid larger jpeg-ish via raw bytes already above
        raise


def probe_text(cfg: EndpointConfig) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "model": cfg.model,
        "messages": [{"role": "user", "content": "Reply with exactly: PONG"}],
        "temperature": 0,
        "stream": False,
    }
    if (cfg.token_param or "max_tokens") == "max_tokens":
        body["max_tokens"] = 16
    elif cfg.token_param == "max_completion_tokens":
        body["max_completion_tokens"] = 16
    if cfg.request_profile == "video_rsi":
        body["thinking"] = {"type": "disabled"}
        body["max_tokens"] = 16
        body.pop("max_completion_tokens", None)
    payload, meta = _post_chat(cfg, body=body)
    content = _content_of(payload)
    ok = bool(meta.get("ok")) and bool(content.strip())
    return {
        "role": "planner",
        "model": cfg.model,
        "base_url": cfg.base_url,
        "request_profile": cfg.request_profile,
        "token_param": cfg.token_param,
        "ok": ok,
        "content_excerpt": content[:80],
        **{k: v for k, v in meta.items() if k != "ok"},
        "empty_content": bool(meta.get("ok")) and not content.strip(),
    }


def probe_vision(cfg: EndpointConfig, *, image_path: Optional[Path] = None) -> Dict[str, Any]:
    b64, mime = _tiny_or_file_b64(image_path)
    body: Dict[str, Any] = {
        "model": cfg.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Reply with exactly: PONG and one word about the image."},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }
        ],
        "temperature": 0,
        "stream": False,
    }
    if (cfg.token_param or "max_tokens") == "max_tokens" or cfg.request_profile == "video_rsi":
        body["max_tokens"] = 32
    elif cfg.token_param == "max_completion_tokens":
        body["max_completion_tokens"] = 32
    if cfg.request_profile == "video_rsi":
        body["thinking"] = {"type": "disabled"}
    payload, meta = _post_chat(cfg, body=body)
    content = _content_of(payload)
    ok = bool(meta.get("ok")) and bool(content.strip())
    return {
        "role": "vision",
        "model": cfg.model,
        "base_url": cfg.base_url,
        "request_profile": cfg.request_profile,
        "token_param": cfg.token_param,
        "ok": ok,
        "content_excerpt": content[:80],
        "image_source": str(image_path) if image_path else "synthetic_png",
        **{k: v for k, v in meta.items() if k != "ok"},
        "empty_content": bool(meta.get("ok")) and not content.strip(),
    }


def is_fatal_api_failure(meta: Dict[str, Any]) -> bool:
    http = int(meta.get("http_status") or 0)
    if http in _FATAL_HTTP:
        return True
    fs = str(meta.get("failure_status") or "")
    if fs in ("http_400", "http_401", "http_403", "config_error"):
        return True
    msg = str(meta.get("message") or meta.get("error") or meta.get("detail_scrubbed") or "").lower()
    return any(m in msg for m in _INVALID_MODEL_MARKERS)


def run_preflight(
    *,
    configs: Optional[Dict[str, EndpointConfig]] = None,
    image_path: Optional[Path] = None,
    require_roles: Sequence[str] = ("planner", "vision"),
) -> Dict[str, Any]:
    configs = configs or load_endpoint_configs()
    probes: Dict[str, Any] = {}
    catalog: Dict[str, Any] = {}

    # Prefer vision endpoint for catalog (same host usually)
    cat_cfg = configs.get("vision") or configs.get("planner")
    if cat_cfg and cat_cfg.configured():
        catalog = list_models(cat_cfg)
    else:
        catalog = {"ok": False, "n_models": 0, "model_ids": [], "error": "endpoint not configured"}

    if "planner" in require_roles:
        cfg = configs["planner"]
        if not cfg.configured():
            probes["planner"] = {"ok": False, "error": "planner not configured", "fatal_non_retryable": True}
        else:
            probes["planner"] = probe_text(cfg)
            # empty catalog + invalid model → clear diagnosis
            if not probes["planner"]["ok"] and catalog.get("n_models") == 0:
                probes["planner"]["likely_cause"] = "api_key_has_empty_model_catalog"

    if "vision" in require_roles:
        cfg = configs["vision"]
        if not cfg.configured():
            probes["vision"] = {"ok": False, "error": "vision not configured", "fatal_non_retryable": True}
        else:
            probes["vision"] = probe_vision(cfg, image_path=image_path)
            if not probes["vision"]["ok"] and catalog.get("n_models") == 0:
                probes["vision"]["likely_cause"] = "api_key_has_empty_model_catalog"

    planner_ok = bool((probes.get("planner") or {}).get("ok")) if "planner" in require_roles else True
    vision_ok = bool((probes.get("vision") or {}).get("ok")) if "vision" in require_roles else True
    passed = planner_ok and vision_ok

    # compact catalog (ids only when small interest set)
    interest = [
        i
        for i in (catalog.get("model_ids") or [])
        if any(x in i for x in ("Qwen", "DeepSeek", "Vision", "VL", "OCR"))
    ]
    report = {
        "schema": "v2_api_preflight_v1",
        "passed": passed,
        "planner_ok": planner_ok,
        "vision_ok": vision_ok,
        "catalog": {
            "ok": catalog.get("ok"),
            "n_models": catalog.get("n_models"),
            "interesting_model_ids": interest[:40],
            "http_status": catalog.get("http_status"),
            "error": catalog.get("error") or catalog.get("detail_scrubbed"),
        },
        "probes": probes,
        "env_models": {
            "STORY_LLM_MODEL": os.environ.get("STORY_LLM_MODEL"),
            "STORY_VLM_MODEL": os.environ.get("STORY_VLM_MODEL"),
            "STORY_VLM_REQUEST_PROFILE": os.environ.get("STORY_VLM_REQUEST_PROFILE"),
            "STORY_PLANNER_REQUEST_PROFILE": os.environ.get("STORY_PLANNER_REQUEST_PROFILE"),
        },
        "cost_disclaimer": COST_DISCLAIMER,
        "note": "API keys never included. Fatal 400/401/403 must abort full story loops.",
    }
    if not passed:
        reasons = []
        for role in require_roles:
            p = probes.get(role) or {}
            if not p.get("ok"):
                reasons.append(
                    f"{role}: model={p.get('model')} http={p.get('http_status')} "
                    f"invalid_model={p.get('invalid_model')} auth={p.get('auth_problem')} "
                    f"cause={p.get('likely_cause') or p.get('detail_scrubbed') or p.get('error')}"
                )
        report["failure_summary"] = "; ".join(reasons)
    return report


def require_preflight(**kwargs: Any) -> Dict[str, Any]:
    report = run_preflight(**kwargs)
    if not report.get("passed"):
        raise PreflightError(report.get("failure_summary") or "preflight failed", report=report)
    return report
