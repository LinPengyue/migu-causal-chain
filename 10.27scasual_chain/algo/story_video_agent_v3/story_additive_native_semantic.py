"""One explicit-budget native-video story-opportunity semantic triage.

This intentionally does NOT certify first-LIVE or edit the EDL. It compares
a short *finished-story seam* against a source-video pre-action candidate
using native continuous MP4 input, not frame-only/event-heat heuristics.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .native_broadcast_observer import _source_context_video
from .story_paid_eval import _parse_model_json_lenient, provider_usage

SCHEMA = "v3a_additive_native_video_semantic_review_v1"
VERDICTS = {"SUPPORTS_ADDITION", "REDUNDANT", "UNCERTAIN"}


def review_additive_native_video(
    *,
    api: Any,
    pack: Mapping[str, Any],
    out_dir: Path,
    approved: bool,
    max_calls: int,
    max_cost_usd: float,
) -> Dict[str, Any]:
    """At most one actual provider request, only after explicit opt-in."""
    out: Dict[str, Any] = {
        "schema": SCHEMA,
        "status": "SKIPPED_NOT_EXPLICITLY_AUTHORIZED",
        "source_sha256": pack.get("source_sha256"),
        "native_video_model_input": False,
        "semantic_gain_confirmed": False,
        "first_live_verified": False,
        "edl_modified": False,
        "release_authorized": False,
        "n_http_calls": 0,
    }

    def finish(status: str) -> Dict[str, Any]:
        out["status"] = status
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "native_semantic_review.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        return out

    if not approved:
        return finish("SKIPPED_NOT_EXPLICITLY_AUTHORIZED")
    usage_before = provider_usage(api)
    initial_calls = int(usage_before.get("http_attempts") or 0)
    initial_cost = float(usage_before.get("est_cost_usd_real") or 0.0)
    if initial_calls >= max_calls or initial_cost >= max_cost_usd:
        return finish("SKIPPED_SHARED_PROVIDER_BUDGET_EXHAUSTED")
    items = list(pack.get("review_items") or [])
    if not items:
        return finish("NO_SOURCE_VIDEO_OPPORTUNITY")
    item = items[0]
    context = (item.get("finished_story_context") or {})
    clips = [
        x for x in (item.get("source_context_clips") or [])
        if (x.get("export") or {}).get("ok")
    ]
    if not context.get("ok") or not clips:
        return finish("MISSING_CONTINUOUS_VIDEO_EVIDENCE")
    # Prefer nearest pre-action source context as a retrieval prior.
    # This is NOT narrative-fit evidence or first-LIVE proof.
    chosen = sorted(clips, key=lambda x: float(x.get("media_out") or 0))[-1]
    source_path = Path(str((chosen.get("export") or {}).get("path") or ""))
    story_path = Path(str(context.get("path") or ""))
    if not source_path.is_file() or not story_path.is_file():
        return finish("MISSING_CLIP_FILES")
    if not (0 < source_path.stat().st_size < 25_000_000
            and 0 < story_path.stat().st_size < 25_000_000):
        return finish("SOURCE_CLIP_PAYLOAD_UNSAFE")
    out["candidate_source_pts"] = [
        chosen.get("media_in"), chosen.get("media_out")
    ]
    out["opportunity_id"] = item.get("opportunity_id")
    # Compress each continuous input to the same small native format as the
    # already deployed broadcast observer; don't concatenate discrete scenes.
    out_dir.mkdir(parents=True, exist_ok=True)
    story_video = _source_context_video(
        source_mp4=story_path, begin=0.0, end=16.0,
        output=out_dir / "story_seam_native_360p.mp4",
    )
    source_video = _source_context_video(
        source_mp4=source_path, begin=0.0, end=11.0,
        output=out_dir / "candidate_source_native_360p.mp4",
    )
    if not (story_video.get("ok") and source_video.get("ok")):
        out["clip_error"] = {"story": story_video, "source": source_video}
        return finish("NATIVE_COMPRESSION_FAILED")
    out["input_video_shas"] = [
        story_video.get("sha256"), source_video.get("sha256")
    ]
    prompt = (
        "You are critiquing a football story edit. There are EXACTLY TWO "
        "continuous videos, in order: VIDEO_1 is a 16-second segment across "
        "the current finished-story edit seam (baseline); VIDEO_2 is an "
        "11-second candidate from the ORIGINAL match broadcast shortly before "
        "the following story action. They are separate source moments. "
        "Watch motion and temporal game state, not just key frames. "
        "Question: does VIDEO_2 provide a SPECIFIC genuinely new story state "
        "or emotional development that would resolve a misleading "
        "implied-causality edit in VIDEO_1? Another random attack or nearby "
        "shot does NOT establish value. A time gap alone is normal editing. "
        "Never infer first-LIVE, replay-free status, team identity, physical "
        "causality or editing benefit from proximity alone. "
        "Return ONLY compact JSON object with keys: verdict "
        "(SUPPORTS_ADDITION|REDUNDANT|UNCERTAIN), "
        "baseline_story_observation, candidate_video_observation, "
        "specific_new_information, concrete_baseline_comparison, "
        "relative_second_in_baseline (0..16), "
        "relative_second_in_candidate (0..11), "
        "replay_or_slowmo_suspected (boolean|null), "
        "uncertainty. For SUPPORTS_ADDITION, all observation fields must "
        "describe identifiable video facts and include relative-second "
        "citations to visible events. If unsure, return UNCERTAIN."
    )
    try:
        def video_url(video):
            return "data:video/mp4;base64," + base64.b64encode(
                Path(str(video["path"])).read_bytes()
            ).decode("ascii")
        response = api.chat(
            role="vision", stats_role="additive_story_native_video",
            messages=[
                {"role": "system",
                 "content": "Watch the provided videos. Answer strict JSON. Admit uncertainty."},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "video_url", "video_url": {"url": video_url(story_video)}},
                    {"type": "video_url", "video_url": {"url": video_url(source_video)}},
                ]},
            ],
            temperature=0.0, allow_degraded_fallback=False,
            cache_key=None,
        )
    except Exception as exc:  # noqa: BLE001
        out["provider_error"] = f"{type(exc).__name__}:{exc}"
        usage_after = provider_usage(api)
        out["n_http_calls"] = max(
            0, int(usage_after.get("http_attempts") or 0)-initial_calls
        )
        out["shared_provider_usage"] = usage_after
        return finish("NATIVE_VIDEO_PROVIDER_FAILED")
    usage_after = provider_usage(api)
    out["n_http_calls"] = max(
        0, int(usage_after.get("http_attempts") or 0)-initial_calls
    )
    out["shared_provider_usage"] = usage_after
    out["provider_mode"] = response.get("provider_mode")
    if str(response.get("provider_mode")) != "real":
        return finish("NATIVE_VIDEO_PROVIDER_NOT_REAL")
    raw = str(response.get("content") or "")
    (out_dir/"original_native_semantic_response.txt").write_text(raw, encoding="utf-8")
    out["native_video_model_input"] = True
    out["model_raw_response_path"] = str(out_dir/"original_native_semantic_response.txt")
    try:
        parsed = _parse_model_json_lenient(raw)
    except (ValueError, TypeError) as exc:
        out["parse_error"] = f"{type(exc).__name__}:{exc}"
        return finish("NATIVE_SEMANTIC_JSON_INVALID")
    if not isinstance(parsed, Mapping):
        return finish("NATIVE_SEMANTIC_JSON_INVALID")
    verdict = str(parsed.get("verdict") or "UNCERTAIN").upper()
    if verdict not in VERDICTS:
        verdict = "UNCERTAIN"
    # Model statements are REVIEW CLAIMS, not independently observed facts.
    out["model_verdict"] = verdict
    out["model_observation"] = dict(parsed)
    try:
        t_base = float(parsed["relative_second_in_baseline"])
        t_cand = float(parsed["relative_second_in_candidate"])
        citations_ok = 0 <= t_base <= 16 and 0 <= t_cand <= 11
    except (KeyError, TypeError, ValueError):
        citations_ok = False
    sufficiently_specific = all(
        isinstance(parsed.get(k), str) and len(parsed[k].strip()) >= 18
        for k in (
            "baseline_story_observation",
            "candidate_video_observation",
            "specific_new_information",
            "concrete_baseline_comparison",
        )
    )
    out["temporal_citations_valid"] = citations_ok
    out["specific_comparison_present"] = sufficiently_specific
    if verdict == "SUPPORTS_ADDITION" and citations_ok and sufficiently_specific:
        # Narrative PRIOR only. Cannot authorize insertion or upgrade safety.
        return finish("MODEL_SUGGESTS_ADDITIVE_NARRATIVE_PRIOR_ONLY")
    if verdict == "REDUNDANT" and citations_ok:
        return finish("MODEL_SUGGESTS_REDUNDANCY_PRIOR_ONLY")
    return finish("NATIVE_SEMANTIC_REVIEW_UNRESOLVED")
