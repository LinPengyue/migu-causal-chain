"""No-billing transport preflight for failed V3-A source-video VLM requests.

Default is LOCAL ONLY: reconstitute exactly the vision JSON message/image
structure and measure payload bytes, but never send it. Optional --probe
performs unauthenticated GET /models over environment-proxy and/or direct
HTTPS (NO /chat/completions POST, NO API key). A 401 or 404 is NOT evidence
that a multimodal POST or model is healthy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from story_video_agent.api_provider import (
    ApiProvider, _encode_image, frame_time_binding_text, load_endpoint_configs,
)
from .remote_vlm_verify import _goal_verify_prompt

SCHEMA = "v3a_stage3_transport_preflight_v1"


def _masked_endpoint(url: str) -> str:
    split = urllib.parse.urlsplit(url)
    host = split.hostname or ""
    port = ":" + str(split.port) if split.port else ""
    return f"{split.scheme}://{host}{port}{split.path.rstrip('/')}"


def _safe_host_proxy(proxy: str) -> str:
    try:
        split = urllib.parse.urlsplit(proxy if "://" in proxy else "http://" + proxy)
        host = split.hostname or ""
        port = ":" + str(split.port) if split.port else ""
        return f"{split.scheme}://{host}{port}"
    except (ValueError, TypeError):
        return "configured_redacted"


def _hash_body_shape(frames: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Report only metadata; image bytes/key/full JSON never written to disk."""
    paths = [Path(str(x.get("path") or "")) for x in frames]
    missing = [i for i, p in enumerate(paths) if not p.is_file()]
    if missing:
        raise FileNotFoundError("missing_frame_files_indices:" + ",".join(map(str, missing)))
    return {
        "frame_count": len(paths),
        "jpeg_bytes": [p.stat().st_size for p in paths],
        "jpeg_total_bytes": sum(p.stat().st_size for p in paths),
        "frame_pts": [
            x.get("actual_media_sec", x.get("requested_media_sec"))
            for x in frames
        ],
    }


def request_metadata(
    *, frames: Sequence[Mapping[str, Any]],
    score_before: Sequence[int],
    score_after: Sequence[int],
    issue_id: str,
    media_in: float,
    media_out: float,
    token_cap: int = 2048,
) -> Dict[str, Any]:
    """Reproduce production's user text/frame binding/base64 JSON body locally."""
    cfg = load_endpoint_configs()["vision"]
    api = ApiProvider(force_mock=True, max_calls=0, max_completion_tokens=token_cap)
    frame_ids = [str(f["frame_id"]) for f in frames]
    prompt = _goal_verify_prompt(
        gap_id=issue_id, media_in=media_in, media_out=media_out,
        score_before=score_before, score_after=score_after,
        attacking_team_hint="side that increases in supplied score transition",
        frame_ids=frame_ids, round_name="round1_dense",
    )
    content = [{
        "type": "text",
        "text": prompt + " Use only program-provided frame_id / media_time fields; never invent media timestamps.",
    }]
    for row, fid in zip(frames, frame_ids):
        bound = {
            "frame_id": fid,
            "requested_media_sec": row.get("requested_media_sec"),
            "actual_media_sec": row.get("actual_media_sec"),
            "pts_status": row.get("pts_status"),
        }
        content.append({"type": "text", "text": frame_time_binding_text(bound, fid)})
        content.append({
            "type": "image_url",
            "image_url": {"url": _encode_image(Path(str(row["path"])))},
        })
    body, audit = api.build_chat_request_body(
        cfg,
        messages=[
            {"role": "system", "content": "Reply with strict JSON only."},
            {"role": "user", "content": content},
        ],
        temperature=cfg.default_temperature if cfg.default_temperature is not None else 0.1,
    )
    # JSON encoder exactly matches ApiProvider._post_chat().
    raw = json.dumps(body).encode("utf-8")
    return {
        "schema": SCHEMA, "network_calls": 0,
        "model": cfg.model,
        "base_url_masked": _masked_endpoint(cfg.base_url),
        "frames": _hash_body_shape(frames),
        "json_post_body_bytes": len(raw),
        "json_post_body_mib": round(len(raw) / 1024 ** 2, 3),
        "sha256_of_unsent_body": hashlib.sha256(raw).hexdigest(),
        "api_request_audit_no_secret": audit,
        "contains_image_base64_in_report": False,
        "contains_api_key_in_report": False,
        "not_evidence_of_usable_proxy_or_model": True,
    }


def unauthenticated_https_probe(
    *, base_url: str, proxy_mode: str, timeout_sec: float = 8.0,
) -> Dict[str, Any]:
    """At most one HTTPS GET /models, no Authorization, no generation or billing.

    A 401/403/404/405 proves only that HTTP response was received; not that
    the credential, body upload, vision model, or /chat/completions works.
    """
    if proxy_mode not in ("env", "direct"):
        raise ValueError("proxy_mode must be env or direct")
    url = base_url.rstrip("/") + "/models"
    split = urllib.parse.urlsplit(url)
    if split.scheme != "https" or not split.hostname:
        return {
            "mode": proxy_mode, "status": "SKIPPED_NON_HTTPS_ENDPOINT",
            "network_calls": 0,
        }
    if proxy_mode == "direct":
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler()
        )
    else:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(), urllib.request.HTTPSHandler()
        )
    request = urllib.request.Request(
        url, method="GET",
        headers={"Accept": "application/json", "User-Agent": "V3A-ZeroBilling-Preflight/1.0"},
    )
    info: Dict[str, Any] = {
        "mode": proxy_mode,
        "method": "GET",
        "resource": "/models",
        "credentials": "NONE",
        "generation_post_sent": False,
        "request_body_bytes": 0,
        "network_calls": 1,
        "status": "UNREACHABLE",
    }
    try:
        with opener.open(request, timeout=timeout_sec) as response:
            info["http_status"] = int(response.status)
            info["status"] = "HTTP_RESPONSE_REACHED"
    except urllib.error.HTTPError as exc:
        info["http_status"] = int(exc.code)
        info["status"] = "HTTP_RESPONSE_REACHED_NO_AUTH"
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        lower = str(exc).lower()
        info["status"] = (
            "PROXY_TUNNEL_FAILED" if "tunnel connection failed" in lower
            else "TLS_ERROR" if ("ssl" in lower or "certificate" in lower)
            else "DNS_ERROR" if ("name resolution" in lower or "name or service" in lower)
            else "NETWORK_ERROR"
        )
        info["error_type"] = type(exc).__name__
        # Do not leak possible proxy credentials/userinfo in exception strings.
    info["not_proof_of_multimodal_post_success"] = True
    return info


def run(
    *,
    frame_json: Path,
    source_queue_json: Path,
    out_json: Path,
    probe: str = "none",
) -> Dict[str, Any]:
    frames = json.loads(frame_json.read_text(encoding="utf-8"))
    if not isinstance(frames, list) or not frames or not all(
        isinstance(x, dict) and x.get("frame_id") for x in frames
    ):
        raise ValueError("invalid_round1_frames_json")
    queue = json.loads(source_queue_json.read_text(encoding="utf-8"))
    issues = [
        x for x in queue.get("issues") or []
        if isinstance(x, dict) and x.get("score_before") and x.get("score_after")
    ]
    if len(issues) != 1:
        raise ValueError("expected_one_independent_score_gap_issue")
    issue = issues[0]
    candidates = [
        x for x in issue.get("continuous_candidate_clips") or []
        if isinstance(x, dict)
        and x.get("clip_path")
        and x.get("semantic_label") not in ("replay", "wrong_attacking_side")
    ]
    if not candidates:
        raise ValueError("no_stage2_video_candidates")
    chosen = max(candidates, key=lambda x: float(x["media_in"]))
    data = request_metadata(
        frames=frames,
        score_before=issue["score_before"],
        score_after=issue["score_after"],
        issue_id=str(issue["issue_id"]),
        media_in=float(chosen["media_in"]),
        media_out=float(chosen["media_out"]),
    )
    data["case"] = "B_RAW_EVENTS_ONLY"
    data["candidate_id"] = chosen["candidate_id"]
    data["probe_status"] = "NOT_REQUESTED"
    data["proxy_settings"] = {
        k: _safe_host_proxy(v)
        for k, v in urllib.request.getproxies().items()
        if k in ("http", "https", "all")
    }
    data["no_secret_proxy_value_logged"] = True
    if probe not in ("none", "env", "direct", "both"):
        raise ValueError("probe must be none/env/direct/both")
    modes = {"none": (), "env": ("env",), "direct": ("direct",),
             "both": ("env", "direct")}[probe]
    data["https_get_probes"] = [
        unauthenticated_https_probe(
            base_url=load_endpoint_configs()["vision"].base_url,
            proxy_mode=mode,
        )
        for mode in modes
    ]
    data["probe_status"] = "ZERO_BILLING_GET_ONLY" if modes else "OFFLINE_ONLY"
    data["total_network_requests"] = len(modes)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    if out_json.exists():
        raise FileExistsError("refuse_overwrite_existing_network_diagnosis")
    out_json.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return data


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Zero-billing V3-A VLM transport diagnosis")
    p.add_argument("--round1-frames", type=Path, required=True)
    p.add_argument("--stage2-queue", type=Path, required=True)
    p.add_argument("--out-json", type=Path, required=True)
    p.add_argument(
        "--probe", choices=("none", "env", "direct", "both"),
        default="none",
        help="Optional unauthenticated HTTPS GET /models, never chat/completions",
    )
    a = p.parse_args(argv)
    result = run(
        frame_json=a.round1_frames,
        source_queue_json=a.stage2_queue,
        out_json=a.out_json,
        probe=a.probe,
    )
    print(json.dumps({
        "status": result["probe_status"],
        "model": result["model"],
        "json_post_body_bytes_unsent": result["json_post_body_bytes"],
        "frames": result["frames"]["frame_count"],
        "network_requests": result["total_network_requests"],
        "https_get_probes": result["https_get_probes"],
        "report": str(a.out_json),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
