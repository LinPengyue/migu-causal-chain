"""Phase 3B：内部视频时间 / 证据核验 —— 唯一可授予 render eligibility 的路径。

外部 JSON 中的 pipeline_verified / time_pipeline_verified / fact_verified
一律剥离，不得直接抬升 candidate → render_ready。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Sequence, Set

from story_video_agent.media import MediaInfo
from story_video_agent.story_output_schema import (
    NOT_RENDER_READY_TIME,
    build_candidate_edl,
    build_render_ready_edl,
    validate_compose_plan,
    validate_render_ready,
)

GRANTED_BY = "internal_verification_pipeline"
EXTERNAL_TRUST_KEYS = (
    "pipeline_verified",
    "time_pipeline_verified",
    "fact_verified",
    "pipeline_time_verified",
)


def strip_external_trust_flags(obj: Any) -> Any:
    """递归剥离外部可信标记（深拷贝）。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in EXTERNAL_TRUST_KEYS:
                continue
            out[k] = strip_external_trust_flags(v)
        return out
    if isinstance(obj, list):
        return [strip_external_trust_flags(x) for x in obj]
    return obj


def sanitize_plan_trust(plan: Dict[str, Any]) -> Dict[str, Any]:
    """清除 plan 上一切非内部授予的 verified / render_ready 痕迹。"""
    plan = strip_external_trust_flags(copy.deepcopy(plan))
    for seg in plan.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        prov = dict(seg.get("time_provenance") or {})
        if prov.get("granted_by") == GRANTED_BY:
            # strip 会删掉 pipeline_verified；仅内部授予可恢复
            prov["pipeline_verified"] = True
            prov["granted_by"] = GRANTED_BY
        else:
            prov["pipeline_verified"] = False
            prov.pop("granted_by", None)
            # 外部伪造的 render_ready 降回 candidate/blocked
            if seg.get("render_eligibility") == "render_ready":
                seg["render_eligibility"] = "candidate_only"
                br = list(seg.get("blocking_reasons") or [])
                br.append("external_render_ready_stripped")
                seg["blocking_reasons"] = sorted(set(br))
        seg["time_provenance"] = prov
    for ref in plan.get("evidence_refs") or []:
        if isinstance(ref, dict) and ref.get("kind") == "verified":
            if ref.get("granted_by") != GRANTED_BY:
                ref["kind"] = "vlm_observation"
                ref["used_as_fact"] = False
                ref["pipeline_verified"] = False
            else:
                ref["pipeline_verified"] = True
    # 重建 EDL，防止 candidate 字段伪造混入 render_ready_edl
    segs = plan.get("segments") or []
    plan["candidate_edl"] = build_candidate_edl(segs)
    plan["render_ready_edl"] = build_render_ready_edl(segs)
    plan["edl"] = plan["candidate_edl"]
    # 仅当重建后仍有内部授予行才可能为 true；默认先 False，由调用方 validate
    from story_video_agent.story_output_schema import validate_render_ready

    ok, _ = validate_render_ready(plan)
    plan["render_ready"] = bool(ok)
    return plan


def verify_windows_against_media(
    segments: Sequence[Dict[str, Any]],
    media: MediaInfo,
) -> List[Dict[str, Any]]:
    """核验每个片段时间窗是否落在真实视频区间；不授予成片资格。"""
    records: List[Dict[str, Any]] = []
    dur = float(media.duration_sec)
    start0 = float(media.start_time_sec or 0.0)
    for seg in segments:
        sid = seg.get("segment_id")
        tin = seg.get("media_in")
        tout = seg.get("media_out")
        rec: Dict[str, Any] = {
            "segment_id": sid,
            "beat": seg.get("beat"),
            "role": seg.get("role"),
            "media_in": tin,
            "media_out": tout,
            "time_status": seg.get("time_status"),
            "render_eligibility": seg.get("render_eligibility"),
            "in_media_bounds": False,
            "ok_for_preview_cut": False,
            "blocking": [],
            "media_duration_sec": dur,
            "media_start_time_sec": start0,
        }
        if tin is None or tout is None:
            rec["blocking"].append("missing_time_window")
            records.append(rec)
            continue
        try:
            a, b = float(tin), float(tout)
        except (TypeError, ValueError):
            rec["blocking"].append("non_numeric_time")
            records.append(rec)
            continue
        if not (a < b):
            rec["blocking"].append("start_not_before_end")
        # 相对媒体时间轴 [0, duration]（ffmpeg -ss 相对文件开始）
        if a < -1e-3 or b > dur + 1e-3:
            rec["blocking"].append(
                f"out_of_bounds:[{a},{b}] not in [0,{dur}]"
            )
        if seg.get("render_eligibility") == "blocked":
            rec["blocking"].append("segment_blocked")
        if seg.get("time_status") in (
            "pending_localization",
            "pending_review",
            "unavailable",
        ):
            rec["blocking"].append(f"time_status:{seg.get('time_status')}")
        rec["in_media_bounds"] = not any(
            x.startswith("out_of_bounds") or x in ("non_numeric_time", "start_not_before_end")
            for x in rec["blocking"]
        )
        # preview 可裁切：有数值窗且在界内，即使 candidate_only
        rec["ok_for_preview_cut"] = (
            rec["in_media_bounds"]
            and "missing_time_window" not in rec["blocking"]
            and seg.get("render_eligibility") != "blocked"
            and seg.get("time_status")
            not in ("pending_localization", "pending_review", "unavailable")
        )
        records.append(rec)
    return records


def apply_internal_verification(
    plan: Dict[str, Any],
    media: MediaInfo,
    *,
    promote_to_render_ready: bool = False,
    required_roles: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """内部核验。

    - 始终：剥离外部信任、记录时间界内检查
    - promote_to_render_ready=True 时：仅对通过内部检查的关键 live 进球片段授予
      granted_by=internal_verification_pipeline（仍要求角色门禁）
    - 伪造字段无法绕过：先 sanitize
    """
    plan = sanitize_plan_trust(plan)
    records = verify_windows_against_media(plan.get("segments") or [], media)
    by_id = {r["segment_id"]: r for r in records}
    plan.setdefault("diagnostics", {})
    plan["diagnostics"]["internal_time_verification"] = {
        "granted_by_authority": GRANTED_BY,
        "media": media.to_dict(),
        "records": records,
        "promote_requested": bool(promote_to_render_ready),
    }

    if not promote_to_render_ready:
        plan["render_ready_edl"] = []
        plan["render_ready"] = False
        plan["verification_status"] = plan.get("verification_status") or "not_render_ready"
        return plan

    need = set(
        required_roles
        or ("equalizer_goal_action", "go_ahead_goal_action")
    )
    promoted: Set[str] = set()
    for seg in plan.get("segments") or []:
        sid = seg.get("segment_id")
        rec = by_id.get(sid) or {}
        role = seg.get("role")
        if role not in need:
            continue
        if seg.get("shot_kind") != "live":
            continue
        if not rec.get("in_media_bounds"):
            continue
        if seg.get("time_status") in NOT_RENDER_READY_TIME:
            continue
        if not seg.get("event_ids"):
            continue
        # 内部授予
        prov = dict(seg.get("time_provenance") or {})
        prov["pipeline_verified"] = True
        prov["granted_by"] = GRANTED_BY
        prov["media_path"] = media.path
        prov["media_duration_sec"] = media.duration_sec
        seg["time_provenance"] = prov
        seg["render_eligibility"] = "render_ready"
        drop = {
            "goal_action_time_not_pipeline_verified",
            "awaiting_internal_media_verification",
            "external_render_ready_stripped",
        }
        br = [b for b in (seg.get("blocking_reasons") or []) if b not in drop]
        seg["blocking_reasons"] = br
        promoted.add(str(role))

    plan["render_ready_edl"] = build_render_ready_edl(plan.get("segments") or [])
    plan["candidate_edl"] = build_candidate_edl(plan.get("segments") or [])
    plan["edl"] = plan["candidate_edl"]
    ok, problems = validate_render_ready(plan)
    # 必须覆盖全部 required roles
    if need - promoted:
        ok = False
        problems = list(problems) + [f"unpromoted_roles:{sorted(need - promoted)}"]
    plan["render_ready"] = bool(ok)
    plan["diagnostics"]["internal_time_verification"]["promoted_roles"] = sorted(promoted)
    plan["diagnostics"]["internal_time_verification"]["render_problems"] = problems
    if plan["render_ready"]:
        plan["verification_status"] = "structure_ok"
        plan["blocking_reasons"] = [
            b
            for b in (plan.get("blocking_reasons") or [])
            if "not_render_ready" not in b and "missing_trusted_goal" not in b
        ]
    else:
        plan["verification_status"] = "not_render_ready"
        plan["render_ready_edl"] = []  # 不完整则清空，防半成品 final
    struct_ok, struct_problems = validate_compose_plan(plan)
    plan["structure_ok"] = struct_ok
    plan["diagnostics"]["structure_ok"] = struct_ok
    plan["diagnostics"]["structure_problems"] = struct_problems
    return plan


def assert_not_forged_render_ready(plan: Dict[str, Any]) -> None:
    """candidate 字段伪造检测：无内部 granted_by 却声称 render_ready → 错误。"""
    for seg in plan.get("segments") or []:
        if seg.get("render_eligibility") != "render_ready":
            continue
        prov = seg.get("time_provenance") or {}
        if prov.get("granted_by") != GRANTED_BY or not prov.get("pipeline_verified"):
            raise ValueError(
                f"forged render_ready on {seg.get('segment_id')}: "
                "missing internal_verification_pipeline grant"
            )
    for row in plan.get("render_ready_edl") or []:
        # row 必须能在 segments 中找到内部授予
        sid = row.get("segment_id")
        seg = next(
            (s for s in (plan.get("segments") or []) if s.get("segment_id") == sid),
            None,
        )
        if not seg:
            raise ValueError(f"render_ready_edl orphan segment {sid}")
        prov = seg.get("time_provenance") or {}
        if prov.get("granted_by") != GRANTED_BY:
            raise ValueError(f"forged render_ready_edl row {sid}")
