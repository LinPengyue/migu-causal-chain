"""Phase 3B/4A 核验门禁：外部 JSON 字段不可信；三轴分离。

三轴：
  1) media_time   — 时间窗是否在视频界内（仅表示可裁切）
  2) semantic     — 是否语义上为目标进球/事件（≠ 界内）
  3) render_grant — 正式成片授权（须媒体+语义均通过，且持有签名核验记录）

任何外部提供的 granted_by / pipeline_verified / time_pipeline_verified /
render_eligibility=render_ready 均不能作为授权凭据。重新加载 JSON 时必须
用 ledger 签名 + 当前 MediaInfo 重新验证，不能只比对字段字符串。
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

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
# 外部 JSON 中即便写了这些也不能恢复信任
EXTERNAL_GRANT_KEYS = (
    "granted_by",
    "grant_record_id",
    "grant_mac",
    "verification_record_id",
)

SEMANTIC_PASSED = "passed"
SEMANTIC_FAILED = "failed"
SEMANTIC_UNRESOLVED = "unresolved"

# 生产语义权威（模型 goal 标签 / observation_heuristic 不在此列）
PRODUCTION_SEMANTIC_AUTHORITIES = frozenset(
    {
        "human_audited_review",
        "independent_verification_pipeline",
    }
)
TEST_SEMANTIC_AUTHORITY = "unit_test"
OBSERVATION_SEMANTIC_AUTHORITY = "observation_only"


class VerificationConfigError(RuntimeError):
    """生产核验密钥 / 权威配置错误。"""


def verify_key_is_persistent() -> bool:
    return bool((os.environ.get("STORY_INTERNAL_VERIFY_KEY") or "").strip())


def _signing_key() -> bytes:
    """持久密钥优先；否则 ephemeral（仅防同进程伪造字符串，不可用于生产授权）。"""
    raw = (os.environ.get("STORY_INTERNAL_VERIFY_KEY") or "").strip()
    if raw:
        return raw.encode("utf-8")
    # 注意：每次解释器启动不同 → JSON 跨进程无法复用（刻意）
    return hashlib.sha256(
        f"sva-ephemeral:{uuid.uuid4().hex}:{os.getpid()}".encode()
    ).digest()


# 模块加载时固定本进程 key（测试可在设 env 后 reload；生产须启动前设好）
_PROCESS_KEY = _signing_key()
_PROCESS_KEY_PERSISTENT = verify_key_is_persistent()


def refresh_signing_key_from_env() -> None:
    """测试辅助：在设置 STORY_INTERNAL_VERIFY_KEY 后刷新模块密钥。"""
    global _PROCESS_KEY, _PROCESS_KEY_PERSISTENT
    _PROCESS_KEY = _signing_key()
    _PROCESS_KEY_PERSISTENT = verify_key_is_persistent()


def _media_content_digest(media: MediaInfo) -> str:
    """内容感知摘要：防止仅改文件内容、元数据不变时复用旧授权。

    对大文件采样 head/mid/tail；虚拟路径则用 path|size|duration 合成。
    """
    path = Path(str(media.path))
    h = hashlib.sha256()
    h.update(str(media.path).encode("utf-8"))
    h.update(str(int(media.size_bytes or 0)).encode("utf-8"))
    h.update(f"{float(media.duration_sec):.6f}".encode("utf-8"))
    if not path.is_file():
        h.update(b"virtual-or-missing")
        return h.hexdigest()
    try:
        size = path.stat().st_size
        h.update(str(size).encode("utf-8"))
        with path.open("rb") as fh:
            head = fh.read(1024 * 256)
            h.update(head)
            if size > 1024 * 512:
                mid = max(0, size // 2 - 128 * 1024)
                fh.seek(mid)
                h.update(fh.read(1024 * 256))
                tail_off = max(0, size - 1024 * 256)
                fh.seek(tail_off)
                h.update(fh.read(1024 * 256))
    except OSError:
        h.update(b"unreadable")
    return h.hexdigest()


def _media_fingerprint(media: MediaInfo) -> Dict[str, Any]:
    return {
        "path": str(media.path),
        "duration_sec": round(float(media.duration_sec), 6),
        "size_bytes": int(media.size_bytes or 0),
        "width": int(media.width or 0),
        "height": int(media.height or 0),
        "fps": round(float(media.fps or 0.0), 6),
        "video_codec": str(media.video_codec or ""),
        "content_sha256": _media_content_digest(media),
    }


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _mac_payload(payload: Dict[str, Any]) -> str:
    return hmac.new(_PROCESS_KEY, _canonical(payload), hashlib.sha256).hexdigest()


def strip_external_trust_flags(obj: Any) -> Any:
    """递归剥离外部可信标记与授权字段（深拷贝）。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in EXTERNAL_TRUST_KEYS or k in EXTERNAL_GRANT_KEYS:
                continue
            # 嵌套 time_provenance / semantic_verification 内的授权串一并清掉
            out[k] = strip_external_trust_flags(v)
        return out
    if isinstance(obj, list):
        return [strip_external_trust_flags(x) for x in obj]
    return obj


def _force_demote_segment(seg: Dict[str, Any], reason: str) -> None:
    if seg.get("render_eligibility") == "render_ready":
        seg["render_eligibility"] = "candidate_only"
    prov = dict(seg.get("time_provenance") or {})
    prov["pipeline_verified"] = False
    prov.pop("granted_by", None)
    prov.pop("grant_record_id", None)
    prov.pop("grant_mac", None)
    seg["time_provenance"] = prov
    # 外部伪造的 semantic passed 也降级（无 MAC 的不算）
    sem = dict(seg.get("semantic_verification") or {})
    if sem:
        if not sem.get("mac") or not _verify_semantic_record(sem, seg):
            sem["status"] = SEMANTIC_UNRESOLVED
            sem["external_stripped"] = True
            sem.pop("mac", None)
            sem.pop("record_id", None)
            seg["semantic_verification"] = sem
    br = list(seg.get("blocking_reasons") or [])
    br.append(reason)
    seg["blocking_reasons"] = sorted(set(br))


def sanitize_plan_trust(plan: Dict[str, Any]) -> Dict[str, Any]:
    """清除 plan 上一切外部信任痕迹；绝不因 JSON 中的 granted_by 字符串恢复授权。"""
    # 先取出 ledger（strip 会删掉嵌套 mac 字段名以外的内容；ledger 整表保留后单独校验）
    raw_ledger = copy.deepcopy(
        ((plan.get("diagnostics") or {}).get("internal_grant_ledger")) or []
    )
    plan = strip_external_trust_flags(copy.deepcopy(plan))
    for seg in plan.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        _force_demote_segment(seg, "external_trust_stripped")
    for ref in plan.get("evidence_refs") or []:
        if not isinstance(ref, dict):
            continue
        if ref.get("kind") == "verified":
            ref["kind"] = "vlm_observation"
        ref["used_as_fact"] = False
        ref["pipeline_verified"] = False
        ref.pop("granted_by", None)

    segs = plan.get("segments") or []
    plan["candidate_edl"] = build_candidate_edl(segs)
    plan["render_ready_edl"] = []  # 必须经 revalidate / apply 才能重建
    plan["edl"] = plan["candidate_edl"]
    plan["render_ready"] = False
    plan.setdefault("diagnostics", {})
    # 保留原始 ledger 副本供 revalidate；未校验前不算有效
    plan["diagnostics"]["internal_grant_ledger_untrusted"] = raw_ledger
    plan["diagnostics"]["internal_grant_ledger"] = []
    plan["diagnostics"]["trust_sanitize"] = {
        "note": "external granted_by/pipeline_verified/render_ready ignored",
        "stripped": True,
    }
    return plan


def verify_windows_against_media(
    segments: Sequence[Dict[str, Any]],
    media: MediaInfo,
) -> List[Dict[str, Any]]:
    """媒体时间轴核验：界内 ⇒ 可裁切；不表示包含目标进球，不授予成片。"""
    records: List[Dict[str, Any]] = []
    dur = float(media.duration_sec)
    start0 = float(media.start_time_sec or 0.0)
    fp = _media_fingerprint(media)
    for seg in segments:
        sid = seg.get("segment_id")
        tin = seg.get("media_in")
        tout = seg.get("media_out")
        rec: Dict[str, Any] = {
            "axis": "media_time",
            "segment_id": sid,
            "beat": seg.get("beat"),
            "role": seg.get("role"),
            "media_in": tin,
            "media_out": tout,
            "time_status": seg.get("time_status"),
            "in_media_bounds": False,
            "ok_for_preview_cut": False,
            "grants_render": False,  # 明确：界内 ≠ 成片授权
            "blocking": [],
            "media_fingerprint": fp,
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
        if a < -1e-3 or b > dur + 1e-3:
            rec["blocking"].append(f"out_of_bounds:[{a},{b}] not in [0,{dur}]")
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
        rec["ok_for_preview_cut"] = (
            rec["in_media_bounds"]
            and "missing_time_window" not in rec["blocking"]
            and seg.get("render_eligibility") != "blocked"
            and seg.get("time_status")
            not in ("pending_localization", "pending_review", "unavailable")
        )
        records.append(rec)
    return records


def _semantic_payload(
    *,
    segment_id: str,
    role: str,
    media_in: Any,
    media_out: Any,
    status: str,
    method: str,
    authority: str,
    frame_ids: Sequence[str],
    media_fp: Dict[str, Any],
    note: str,
) -> Dict[str, Any]:
    return {
        "segment_id": segment_id,
        "role": role,
        "media_in": media_in,
        "media_out": media_out,
        "status": status,
        "method": method,
        "authority": authority,
        "evidence_frame_ids": list(frame_ids),
        "media_fingerprint": media_fp,
        "note": note,
    }


def _verify_semantic_record(sem: Dict[str, Any], seg: Dict[str, Any]) -> bool:
    mac = sem.get("mac")
    if not mac:
        return False
    payload = _semantic_payload(
        segment_id=str(seg.get("segment_id")),
        role=str(seg.get("role") or sem.get("role") or ""),
        media_in=sem.get("media_in"),
        media_out=sem.get("media_out"),
        status=str(sem.get("status")),
        method=str(sem.get("method") or ""),
        authority=str(sem.get("authority") or ""),
        frame_ids=list(sem.get("evidence_frame_ids") or []),
        media_fp=dict(sem.get("media_fingerprint") or {}),
        note=str(sem.get("note") or ""),
    )
    if float(sem.get("media_in") or -1) != float(seg.get("media_in") or -2):
        return False
    if float(sem.get("media_out") or -1) != float(seg.get("media_out") or -2):
        return False
    expected = _mac_payload(payload)
    return hmac.compare_digest(str(mac), expected)


def attest_semantic_result(
    seg: Dict[str, Any],
    media: MediaInfo,
    *,
    status: str,
    method: str,
    frame_ids: Optional[Sequence[str]] = None,
    note: str = "",
    authority: str = TEST_SEMANTIC_AUTHORITY,
) -> Dict[str, Any]:
    """语义结果签发函数（HMAC 绑定）——不等于完成视觉事实核验。

    - status=passed 仅表示「签发方主张通过」，须配合合法 authority
    - 生产成片授权仅接受 human_audited_review / independent_verification_pipeline
    - 模型 goal 标签、observation_heuristic、unit_test 均不能单独触发生产授权
    """
    if status not in (SEMANTIC_PASSED, SEMANTIC_FAILED, SEMANTIC_UNRESOLVED):
        raise ValueError(f"invalid semantic status: {status}")
    # 禁止把模型标签方法伪装成生产权威
    method_l = (method or "").lower()
    if authority in PRODUCTION_SEMANTIC_AUTHORITIES and any(
        x in method_l for x in ("vlm", "model_label", "mock", "observation_heuristic")
    ):
        raise VerificationConfigError(
            "production semantic authority cannot use model/mock/observation methods"
        )
    fp = _media_fingerprint(media)
    fids = list(frame_ids or seg.get("frame_ids") or [])
    payload = _semantic_payload(
        segment_id=str(seg.get("segment_id")),
        role=str(seg.get("role") or ""),
        media_in=seg.get("media_in"),
        media_out=seg.get("media_out"),
        status=status,
        method=method,
        authority=authority,
        frame_ids=fids,
        media_fp=fp,
        note=note,
    )
    record = {
        **payload,
        "record_id": f"sem_{uuid.uuid4().hex[:16]}",
        "mac": _mac_payload(payload),
        "axis": "semantic",
        "issued_at": time.time(),
        "disclaimer": (
            "attest_semantic_result signs a claim; it does not by itself prove "
            "visual goal facts. Model goal labels must not grant render_ready."
        ),
    }
    seg["semantic_verification"] = record
    return record


def evaluate_semantic_from_observations(
    seg: Dict[str, Any],
    media: MediaInfo,
    visual_evidence: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """根据观察层证据给出语义结论（仍不授予 render）。

    - 负向/无关/错误事件 → failed（authority=observation_only）
    - 否则 → unresolved
    - 永不自动 passed；模型 goal 标签不能抬升成片
    """
    role = str(seg.get("role") or "")
    sid = str(seg.get("segment_id") or "")
    related = [
        ev
        for ev in visual_evidence
        if isinstance(ev, dict)
        and (
            ev.get("gap_id")
            and role.replace("_goal_action", "") in str(ev.get("gap_id"))
            or sid in str(ev.get("segment_id") or "")
        )
    ]
    note = "no_related_observation"
    status = SEMANTIC_UNRESOLVED
    frames: List[str] = []
    for ev in related or list(visual_evidence):
        frames.extend(str(x) for x in (ev.get("frame_ids") or []))
        blob = " ".join(
            [
                " ".join(str(a) for a in (ev.get("observed_actions") or [])),
                str(ev.get("story_relation") or ""),
                str(ev.get("notes") or ""),
                str(ev.get("failure_status") or ""),
            ]
        ).lower()
        labels = [str(x).lower() for x in (ev.get("visual_labels") or [])]
        if (
            ev.get("failure_status") == "unrelated_visual"
            or "unrelated" in labels
            or "wrong_goal" in blob
            or "wrong event" in blob
            or "错误进球" in blob
            or "不是目标进球" in blob
        ):
            status = SEMANTIC_FAILED
            note = "negative_or_wrong_goal_observation"
            break
        if ev.get("conflict"):
            status = SEMANTIC_FAILED
            note = "visual_conflict"
            break
        if "goal" in labels or "goal" in blob:
            # 模型标签仅作观察，保持 unresolved
            note = "model_goal_label_observation_only_not_fact"
            status = SEMANTIC_UNRESOLVED
    return attest_semantic_result(
        seg,
        media,
        status=status,
        method="observation_heuristic",
        authority=OBSERVATION_SEMANTIC_AUTHORITY,
        frame_ids=sorted(set(frames)),
        note=note,
    )


def _semantic_authority_allows_grant(
    sem: Dict[str, Any], *, allow_test_semantic: bool
) -> Tuple[bool, str]:
    auth = str(sem.get("authority") or "")
    if auth in PRODUCTION_SEMANTIC_AUTHORITIES:
        return True, "ok"
    if allow_test_semantic and auth == TEST_SEMANTIC_AUTHORITY:
        return True, "ok_test"
    if auth == OBSERVATION_SEMANTIC_AUTHORITY:
        return False, "observation_only_cannot_grant"
    if auth == TEST_SEMANTIC_AUTHORITY:
        return False, "unit_test_authority_requires_allow_test_semantic"
    return False, f"unauthorized_semantic_authority:{auth or 'missing'}"


def _grant_payload(
    *,
    segment_id: str,
    role: str,
    media_in: Any,
    media_out: Any,
    media_fp: Dict[str, Any],
    evidence_frame_ids: Sequence[str],
    semantic_record_id: str,
    method: str,
) -> Dict[str, Any]:
    return {
        "segment_id": segment_id,
        "role": role,
        "media_in": media_in,
        "media_out": media_out,
        "media_fingerprint": media_fp,
        "evidence_frame_ids": list(evidence_frame_ids),
        "semantic_record_id": semantic_record_id,
        "method": method,
        "granted_by": GRANTED_BY,
    }


def _issue_grant_record(
    seg: Dict[str, Any],
    media: MediaInfo,
    *,
    semantic: Dict[str, Any],
    method: str,
) -> Dict[str, Any]:
    fp = _media_fingerprint(media)
    payload = _grant_payload(
        segment_id=str(seg.get("segment_id")),
        role=str(seg.get("role") or ""),
        media_in=seg.get("media_in"),
        media_out=seg.get("media_out"),
        media_fp=fp,
        evidence_frame_ids=list(semantic.get("evidence_frame_ids") or []),
        semantic_record_id=str(semantic.get("record_id") or ""),
        method=method,
    )
    record = {
        **payload,
        "record_id": f"grant_{uuid.uuid4().hex[:16]}",
        "mac": _mac_payload(payload),
        "axis": "render_grant",
        "issued_at": time.time(),
        "verification_result": {
            "media_time": "passed",
            "semantic": semantic.get("status"),
            "render_grant": "passed",
        },
    }
    return record


def _verify_grant_record(
    record: Dict[str, Any],
    seg: Dict[str, Any],
    media: MediaInfo,
) -> Tuple[bool, str]:
    if not record.get("mac") or not record.get("record_id"):
        return False, "missing_mac"
    if record.get("granted_by") != GRANTED_BY:
        return False, "bad_granted_by"
    fp = _media_fingerprint(media)
    # 媒体身份必须一致（含 content_sha256，防内容替换）
    rec_fp = dict(record.get("media_fingerprint") or {})
    for k in ("path", "duration_sec", "size_bytes", "content_sha256"):
        if rec_fp.get(k) != fp.get(k):
            return False, f"media_mismatch:{k}"
    if str(record.get("segment_id")) != str(seg.get("segment_id")):
        return False, "segment_mismatch"
    if float(record.get("media_in") or -1) != float(seg.get("media_in") or -2):
        return False, "window_tampered_in"
    if float(record.get("media_out") or -1) != float(seg.get("media_out") or -2):
        return False, "window_tampered_out"
    sem = seg.get("semantic_verification") or {}
    if not _verify_semantic_record(sem, seg):
        return False, "semantic_mac_invalid"
    if sem.get("status") != SEMANTIC_PASSED:
        return False, "semantic_not_passed"
    if str(record.get("semantic_record_id")) != str(sem.get("record_id") or ""):
        return False, "semantic_record_mismatch"
    payload = _grant_payload(
        segment_id=str(record.get("segment_id")),
        role=str(record.get("role") or ""),
        media_in=record.get("media_in"),
        media_out=record.get("media_out"),
        media_fp=rec_fp,
        evidence_frame_ids=list(record.get("evidence_frame_ids") or []),
        semantic_record_id=str(record.get("semantic_record_id") or ""),
        method=str(record.get("method") or ""),
    )
    if not hmac.compare_digest(str(record.get("mac")), _mac_payload(payload)):
        return False, "mac_mismatch"
    return True, "ok"


def revalidate_plan_grants(
    plan: Dict[str, Any],
    media: MediaInfo,
) -> Dict[str, Any]:
    """根据 ledger 重新验证并仅恢复通过 MAC+媒体绑定的授权。"""
    plan = sanitize_plan_trust(plan)
    # sanitize 把 ledger 挪到 untrusted
    candidates = list(
        (plan.get("diagnostics") or {}).get("internal_grant_ledger_untrusted") or []
    )
    media_recs = verify_windows_against_media(plan.get("segments") or [], media)
    by_id = {r["segment_id"]: r for r in media_recs}
    restored: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    seg_by_id = {s.get("segment_id"): s for s in (plan.get("segments") or [])}

    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        sid = raw.get("segment_id")
        seg = seg_by_id.get(sid)
        if not seg:
            rejected.append({"segment_id": sid, "reason": "missing_segment"})
            continue
        # 需先恢复 semantic 记录到 seg 再验 grant（ledger 可附带 semantic 快照）
        sem_snap = raw.get("semantic_snapshot")
        if isinstance(sem_snap, dict):
            seg["semantic_verification"] = copy.deepcopy(sem_snap)
        ok, reason = _verify_grant_record(raw, seg, media)
        mrec = by_id.get(sid) or {}
        if not mrec.get("in_media_bounds"):
            ok, reason = False, "media_out_of_bounds_on_revalidate"
        if not ok:
            rejected.append({"segment_id": sid, "reason": reason})
            continue
        # 恢复授权
        prov = dict(seg.get("time_provenance") or {})
        prov["pipeline_verified"] = True
        prov["granted_by"] = GRANTED_BY
        prov["grant_record_id"] = raw.get("record_id")
        prov["grant_mac"] = raw.get("mac")
        prov["media_path"] = media.path
        prov["media_duration_sec"] = media.duration_sec
        seg["time_provenance"] = prov
        seg["render_eligibility"] = "render_ready"
        restored.append(raw)

    plan["diagnostics"]["internal_grant_ledger"] = restored
    plan["diagnostics"]["internal_grant_revalidation"] = {
        "restored": [r.get("record_id") for r in restored],
        "rejected": rejected,
        "media": _media_fingerprint(media),
    }
    plan["diagnostics"]["internal_time_verification"] = {
        "granted_by_authority": GRANTED_BY,
        "media": media.to_dict(),
        "records": media_recs,
        "note": "media_time axis only; grants_render always false here",
    }
    plan["render_ready_edl"] = build_render_ready_edl(plan.get("segments") or [])
    plan["candidate_edl"] = build_candidate_edl(plan.get("segments") or [])
    plan["edl"] = plan["candidate_edl"]
    ok, problems = validate_render_ready(plan)
    plan["render_ready"] = bool(ok) and bool(plan["render_ready_edl"])
    if not plan["render_ready"]:
        plan["render_ready_edl"] = []
    plan["diagnostics"]["revalidate_render_problems"] = problems
    return plan


def apply_internal_verification(
    plan: Dict[str, Any],
    media: MediaInfo,
    *,
    promote_to_render_ready: bool = False,
    required_roles: Optional[Sequence[str]] = None,
    visual_evidence: Optional[Sequence[Dict[str, Any]]] = None,
    require_semantic_pass: bool = True,
    allow_test_semantic: bool = False,
) -> Dict[str, Any]:
    """内部核验。

    - 始终剥离外部信任，写入媒体时间轴记录（可裁切 ≠ 成片）
    - promote=True 时：media_ok AND semantic_passed AND 合法 authority AND
      （生产）持久 STORY_INTERNAL_VERIFY_KEY
    - 模型 goal 标签 / observation_only 不能授权
    - allow_test_semantic=True 仅用于单元测试（authority=unit_test）
    """
    plan = sanitize_plan_trust(plan)
    records = verify_windows_against_media(plan.get("segments") or [], media)
    by_id = {r["segment_id"]: r for r in records}
    plan.setdefault("diagnostics", {})
    plan["diagnostics"]["internal_time_verification"] = {
        "granted_by_authority": GRANTED_BY,
        "media": media.to_dict(),
        "media_fingerprint": _media_fingerprint(media),
        "records": records,
        "promote_requested": bool(promote_to_render_ready),
        "verify_key_persistent": bool(_PROCESS_KEY_PERSISTENT),
        "allow_test_semantic": bool(allow_test_semantic),
        "axes": {
            "media_time": "bounds/cuttable only",
            "semantic": "separate; required for render grant",
            "render_grant": "signed ledger only",
        },
    }

    # 对缺失语义记录的片段给出 unresolved（不自动 passed）
    vis = list(visual_evidence or [])
    for seg in plan.get("segments") or []:
        sem = seg.get("semantic_verification")
        if sem and _verify_semantic_record(sem, seg):
            continue
        if vis:
            evaluate_semantic_from_observations(seg, media, vis)
        else:
            # 无观察则显式 unresolved，清除伪造
            if not sem or not _verify_semantic_record(sem or {}, seg):
                attest_semantic_result(
                    seg,
                    media,
                    status=SEMANTIC_UNRESOLVED,
                    method="no_observation",
                    authority=OBSERVATION_SEMANTIC_AUTHORITY,
                    note="semantic_unresolved_pending_evidence",
                )

    if not promote_to_render_ready:
        plan["render_ready_edl"] = []
        plan["render_ready"] = False
        plan["verification_status"] = plan.get("verification_status") or "not_render_ready"
        plan["diagnostics"]["internal_grant_ledger"] = []
        return plan

    # 生产授权必须持久密钥；测试路径显式 allow_test_semantic
    if not allow_test_semantic and not _PROCESS_KEY_PERSISTENT:
        plan["render_ready"] = False
        plan["render_ready_edl"] = []
        plan["verification_status"] = "not_render_ready"
        plan["diagnostics"]["internal_grant_ledger"] = []
        plan["diagnostics"]["internal_time_verification"]["promote_blocked"] = (
            "STORY_INTERNAL_VERIFY_KEY not set; refusing production render grants"
        )
        plan["diagnostics"]["internal_time_verification"]["render_problems"] = [
            "missing_persistent_STORY_INTERNAL_VERIFY_KEY"
        ]
        return plan

    need = set(
        required_roles
        or ("equalizer_goal_action", "go_ahead_goal_action")
    )
    promoted: Set[str] = set()
    ledger: List[Dict[str, Any]] = []
    skip_log: List[Dict[str, Any]] = []

    for seg in plan.get("segments") or []:
        sid = seg.get("segment_id")
        rec = by_id.get(sid) or {}
        role = seg.get("role")
        if role not in need:
            continue
        if seg.get("shot_kind") != "live":
            skip_log.append({"segment_id": sid, "reason": "not_live"})
            continue
        if not rec.get("in_media_bounds"):
            skip_log.append({"segment_id": sid, "reason": "media_bounds_failed"})
            continue
        # 界内只说明可裁切
        if not rec.get("ok_for_preview_cut"):
            skip_log.append({"segment_id": sid, "reason": "not_cuttable"})
            continue
        if seg.get("time_status") in NOT_RENDER_READY_TIME:
            skip_log.append({"segment_id": sid, "reason": f"time_status:{seg.get('time_status')}"})
            continue
        if not seg.get("event_ids"):
            skip_log.append({"segment_id": sid, "reason": "missing_event_ids"})
            continue
        sem = seg.get("semantic_verification") or {}
        if require_semantic_pass:
            if not _verify_semantic_record(sem, seg):
                skip_log.append({"segment_id": sid, "reason": "semantic_mac_invalid"})
                continue
            if sem.get("status") != SEMANTIC_PASSED:
                skip_log.append(
                    {
                        "segment_id": sid,
                        "reason": f"semantic_{sem.get('status') or 'missing'}",
                    }
                )
                continue
            ok_auth, auth_reason = _semantic_authority_allows_grant(
                sem, allow_test_semantic=allow_test_semantic
            )
            if not ok_auth:
                skip_log.append({"segment_id": sid, "reason": auth_reason})
                continue
        # 签发正式授权记录
        grant = _issue_grant_record(
            seg,
            media,
            semantic=sem,
            method="internal_media+semantic+role_gate",
        )
        grant["semantic_snapshot"] = copy.deepcopy(sem)
        ledger.append(grant)
        prov = dict(seg.get("time_provenance") or {})
        prov["pipeline_verified"] = True
        prov["granted_by"] = GRANTED_BY
        prov["grant_record_id"] = grant["record_id"]
        prov["grant_mac"] = grant["mac"]
        prov["media_path"] = media.path
        prov["media_duration_sec"] = media.duration_sec
        seg["time_provenance"] = prov
        seg["render_eligibility"] = "render_ready"
        drop = {
            "goal_action_time_not_pipeline_verified",
            "awaiting_internal_media_verification",
            "external_render_ready_stripped",
            "external_trust_stripped",
            "phase4a_observation_unverified",
            "phase4a_pending_review",
        }
        br = [b for b in (seg.get("blocking_reasons") or []) if b not in drop]
        seg["blocking_reasons"] = br
        promoted.add(str(role))

    plan["diagnostics"]["internal_grant_ledger"] = ledger
    plan["diagnostics"]["internal_time_verification"]["promoted_roles"] = sorted(promoted)
    plan["diagnostics"]["internal_time_verification"]["promote_skips"] = skip_log
    plan["render_ready_edl"] = build_render_ready_edl(plan.get("segments") or [])
    plan["candidate_edl"] = build_candidate_edl(plan.get("segments") or [])
    plan["edl"] = plan["candidate_edl"]
    ok, problems = validate_render_ready(plan)
    if need - promoted:
        ok = False
        problems = list(problems) + [f"unpromoted_roles:{sorted(need - promoted)}"]
    # 额外：每个 render_ready 行必须有可验证 grant
    for row in plan.get("render_ready_edl") or []:
        sid = row.get("segment_id")
        seg = next(
            (s for s in (plan.get("segments") or []) if s.get("segment_id") == sid),
            None,
        )
        if not seg:
            ok = False
            problems.append(f"orphan_edl:{sid}")
            continue
        grant = next((g for g in ledger if g.get("segment_id") == sid), None)
        if not grant:
            ok = False
            problems.append(f"missing_grant_record:{sid}")
            continue
        vok, vreason = _verify_grant_record(grant, seg, media)
        if not vok:
            ok = False
            problems.append(f"grant_recheck_failed:{sid}:{vreason}")

    plan["render_ready"] = bool(ok)
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
        plan["render_ready_edl"] = []
        # 降级半成品授权字段，但保留 ledger 供审计（未整体通过则清空授权态）
        for seg in plan.get("segments") or []:
            if seg.get("role") in need:
                _force_demote_segment(seg, "render_gate_incomplete")
        plan["diagnostics"]["internal_grant_ledger"] = []
    struct_ok, struct_problems = validate_compose_plan(plan)
    plan["structure_ok"] = struct_ok
    plan["diagnostics"]["structure_ok"] = struct_ok
    plan["diagnostics"]["structure_problems"] = struct_problems
    return plan


def assert_not_forged_render_ready(
    plan: Dict[str, Any],
    media: Optional[MediaInfo] = None,
) -> None:
    """检测伪造：仅字符串 granted_by / 无有效 MAC 的 render_ready 一律报错。"""
    ledger = {
        g.get("segment_id"): g
        for g in ((plan.get("diagnostics") or {}).get("internal_grant_ledger") or [])
        if isinstance(g, dict)
    }
    for seg in plan.get("segments") or []:
        if seg.get("render_eligibility") != "render_ready":
            continue
        prov = seg.get("time_provenance") or {}
        if prov.get("granted_by") != GRANTED_BY:
            raise ValueError(
                f"forged render_ready on {seg.get('segment_id')}: missing granted_by"
            )
        grant = ledger.get(seg.get("segment_id"))
        if not grant:
            raise ValueError(
                f"forged render_ready on {seg.get('segment_id')}: "
                "no internal_grant_ledger record (string granted_by insufficient)"
            )
        if media is not None:
            ok, reason = _verify_grant_record(grant, seg, media)
            if not ok:
                raise ValueError(
                    f"forged/invalid grant on {seg.get('segment_id')}: {reason}"
                )
    for row in plan.get("render_ready_edl") or []:
        sid = row.get("segment_id")
        if sid not in ledger:
            raise ValueError(f"forged render_ready_edl row {sid}: no ledger record")
