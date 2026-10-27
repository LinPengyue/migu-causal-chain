"""2.6 出站回调：超时 + 重试；失败不抛到主任务。

成功条件：HTTP 2xx 且（无 JSON / 无 code 字段 / code==\"0\"）。
接收方返回 JSON 且 code!=\"0\" 视为业务失败并重试。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("api.callback")


def _business_ok(resp: httpx.Response) -> Tuple[bool, Optional[str]]:
    """HTTP 已 2xx 时再检查业务 code。返回 (ok, error_detail)。"""
    ctype = (resp.headers.get("content-type") or "").lower()
    text = (resp.text or "").strip()
    if not text:
        return True, None
    # 非 JSON 正文：仅按 HTTP 成功
    if "json" not in ctype and not (text.startswith("{") or text.startswith("[")):
        return True, None
    try:
        data = resp.json()
    except Exception:
        # 声称 JSON 但解析失败：保守按失败重试
        return False, f"invalid JSON body: {text[:200]}"
    if not isinstance(data, dict):
        return True, None
    if "code" not in data:
        return True, None
    code = data.get("code")
    if str(code) == "0":
        return True, None
    return False, f"business code={code!r} message={data.get('message')!r}"


def post_callback(
    callback_url: str,
    body: Dict[str, Any],
    *,
    timeout_s: float = 5.0,
    max_attempts: int = 3,
    backoff_s: float = 0.2,
) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "url": callback_url,
        "ok": False,
        "attempts": 0,
        "status_code": None,
        "error": None,
        "highlightType": body.get("highlightType"),
        "result_id": body.get("_result_id"),
        "body_summary": {
            "highlightType": body.get("highlightType"),
            "chainType": body.get("chainType"),
            "n_highlights": len(body.get("highlights") or []),
            "clipIds": [h.get("clipId") for h in (body.get("highlights") or [])],
        },
    }
    payload = {k: v for k, v in body.items() if not str(k).startswith("_")}
    last_err: Optional[str] = None
    for attempt in range(1, max_attempts + 1):
        record["attempts"] = attempt
        try:
            with httpx.Client(timeout=timeout_s) as client:
                resp = client.post(callback_url, json=payload)
            record["status_code"] = resp.status_code
            if 200 <= resp.status_code < 300:
                ok, detail = _business_ok(resp)
                if ok:
                    record["ok"] = True
                    logger.info(
                        "callback ok url=%s attempt=%s type=%s clips=%s",
                        callback_url,
                        attempt,
                        payload.get("highlightType"),
                        record["body_summary"]["clipIds"],
                    )
                    return record
                last_err = detail or "business code != 0"
                logger.warning(
                    "callback business fail url=%s attempt=%s detail=%s",
                    callback_url,
                    attempt,
                    last_err,
                )
            else:
                last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.warning(
                    "callback non-2xx url=%s attempt=%s status=%s",
                    callback_url,
                    attempt,
                    resp.status_code,
                )
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "callback error url=%s attempt=%s err=%s",
                callback_url,
                attempt,
                last_err,
            )
        if attempt < max_attempts:
            time.sleep(backoff_s * attempt)
    record["error"] = last_err
    record["callback_failed"] = True
    logger.error(
        "callback failed after %s attempts url=%s err=%s",
        max_attempts,
        callback_url,
        last_err,
    )
    return record


def post_callbacks(
    callback_url: str,
    bodies: List[Dict[str, Any]],
    *,
    timeout_s: float = 5.0,
    max_attempts: int = 3,
    backoff_s: float = 0.2,
) -> List[Dict[str, Any]]:
    return [
        post_callback(
            callback_url,
            body,
            timeout_s=timeout_s,
            max_attempts=max_attempts,
            backoff_s=backoff_s,
        )
        for body in bodies
    ]
