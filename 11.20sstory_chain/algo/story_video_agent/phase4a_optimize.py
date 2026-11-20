"""Phase 4A：真实多模态理解驱动的故事镜头搜索与候选优化。

流程：seed 窗口抽帧 → VLM 观察 →（规则 / LLM）规划下一窗 → 回填 Verifier/Composer
→ 仅内部核验可抬升 render eligibility → Phase 3B preview v2。

计费门控见 phase4a_config.billing_allowed()；默认 Mock（可对真视频抽帧）。
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from story_video_agent.api_provider import (
    COST_DISCLAIMER,
    ApiConfigError,
    ApiProvider,
    api_enabled,
    load_endpoint_configs,
    resolve_effective_caps,
    smoke_enabled,
)
from story_video_agent.frames import FrameBudget, FrameBudgetExhausted, FrameStore, allocate_gap_caps
from story_video_agent.internal_verification import (
    GRANTED_BY,
    apply_internal_verification,
    sanitize_plan_trust,
    strip_external_trust_flags,
    verify_key_is_persistent,
)
from story_video_agent.media import MediaInfo, probe_video
from story_video_agent.narrative_composer import compose_story_plan
from story_video_agent.phase4a_config import (
    DEFAULT_WINDOW_HALF_SEC,
    EXPERIMENT_MODES,
    FIRST_REAL_VLM_ONLY,
    OFFICIAL_VIDEO_RSI_MODELS,
    SEED_MODE_CROATIA_LEGACY,
    SEED_MODE_STORY,
    SEED_MODES,
    Phase4AConfig,
    billing_allowed,
    load_optional_json,
    parse_targets,
    phase4a_real_enabled,
    resolve_seed_targets,
    select_seed_targets,
)
from story_video_agent.review_assist import build_review_manifest
from story_video_agent.story_output_schema import (
    build_candidate_edl,
    build_render_ready_edl,
    validate_compose_plan,
)
from story_video_agent.story_verifier import classify_visual_evidence, verify_story
from story_video_agent.video_renderer import RenderError, render_story_video
from story_video_agent.vision_provider import VisionProvider

PathLike = Union[str, Path]

# 视觉标签（观察层，≠ verified）
VISUAL_LABELS = (
    "shot",
    "goal",
    "score_change",
    "celebration",
    "replay",
    "scoreboard",
    "unrelated",
    "uncertain",
)


class Phase4AError(RuntimeError):
    """Phase 4A 配置 / 门控错误。"""


def preflight_phase4a(
    *,
    mode: str,
    story_json: Path,
    video_path: Path,
    force_mock: bool,
    require_billing_caps: bool = True,
    max_api_calls: Optional[int] = None,
    max_completion_tokens: Optional[int] = None,
    targets: Optional[Sequence[str]] = None,
    max_rounds: Optional[int] = None,
    frames_per_round: Optional[int] = None,
    frame_budget: Optional[int] = None,
    raise_on_problems: bool = True,
    causal_json: Optional[Path] = None,
    seed_mode: str = SEED_MODE_STORY,
    window_half_sec: Optional[float] = None,
) -> Dict[str, Any]:
    problems: List[str] = []
    if mode not in EXPERIMENT_MODES:
        problems.append(f"unknown mode {mode}; expected {EXPERIMENT_MODES}")
    if not story_json.is_file():
        problems.append(f"story json missing: {story_json}")
    if not video_path.is_file():
        problems.append(f"video missing: {video_path}")
    if causal_json is not None and not Path(causal_json).is_file():
        problems.append(f"causal json missing: {causal_json}")

    selected_targets: Tuple[str, ...] = ()
    try:
        selected_targets = parse_targets(targets)
    except ValueError as exc:
        problems.append(str(exc))

    mode_s = (seed_mode or SEED_MODE_STORY).strip().lower()
    if mode_s not in SEED_MODES:
        problems.append(f"unknown seed_mode {seed_mode!r}; expected {list(SEED_MODES)}")
        mode_s = SEED_MODE_STORY

    want_real = not force_mock
    configs = load_endpoint_configs()
    roles = ["vision"] if mode == "vlm-only" else ["vision", "planner"]
    if want_real:
        if not api_enabled():
            problems.append("STORY_API_ENABLE=1 required for real Phase 4A")
        if not phase4a_real_enabled():
            problems.append("STORY_PHASE4A_REAL=1 required (explicit Phase 4A billing auth)")
        if not smoke_enabled():
            problems.append("STORY_API_SMOKE=1 required for billed Phase 4A")
        for role in roles:
            cfg = configs[role]
            if not cfg.base_url:
                problems.append(f"{role}: missing BASE_URL")
            if not cfg.model:
                problems.append(f"{role}: missing MODEL")
            if not cfg.api_key:
                problems.append(f"{role}: missing API_KEY")
        if require_billing_caps:
            if not (os.environ.get("STORY_API_MAX_CALLS") or "").strip():
                problems.append("STORY_API_MAX_CALLS required")
            if not (os.environ.get("STORY_API_MAX_COST_USD") or "").strip():
                problems.append("STORY_API_MAX_COST_USD required")

    caps = resolve_effective_caps(
        max_calls=max_api_calls,
        max_completion_tokens=max_completion_tokens,
    )
    # 端点摘要：不含 API Key
    endpoints = {r: configs[r].to_dict() for r in ("planner", "vision")}
    request_models = {
        "planner": endpoints["planner"].get("model") or "",
        "vision": endpoints["vision"].get("model") or "",
    }

    story_obj: Optional[Dict[str, Any]] = None
    causal_obj: Optional[Dict[str, Any]] = None
    if story_json.is_file():
        try:
            raw = json.loads(story_json.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                story_obj = raw
            else:
                problems.append("story json root must be object")
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"story json unreadable: {exc}")
    if causal_json is not None and Path(causal_json).is_file():
        try:
            causal_obj = load_optional_json(causal_json)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            problems.append(f"causal json unreadable: {exc}")

    half = (
        float(window_half_sec)
        if window_half_sec is not None
        else float(DEFAULT_WINDOW_HALF_SEC)
    )
    seed_windows: List[Dict[str, Any]] = []
    seed_error: Optional[str] = None
    if selected_targets and "story json missing" not in " ".join(problems):
        try:
            resolved = resolve_seed_targets(
                selected_targets,
                half=half,
                story=story_obj,
                causal=causal_obj,
                seed_mode=mode_s,
            )
            seed_windows = [
                {
                    "target_id": t["target_id"],
                    "seed_center_sec": t.get("seed_center_sec"),
                    "window": t.get("window"),
                    "score_anchor_sec": t.get("score_anchor_sec"),
                    "seed_note": t.get("seed_note"),
                    "kind": t.get("kind"),
                    "seed_provenance": t.get("seed_provenance"),
                }
                for t in resolved
            ]
        except ValueError as exc:
            seed_error = str(exc)
            problems.append(str(exc))

    report = {
        "ok": not problems,
        "mode": mode,
        "force_mock": force_mock,
        "billing_allowed": billing_allowed(),
        "want_real": want_real,
        "problems": problems,
        "cost_disclaimer": COST_DISCLAIMER,
        "http_requests_sent": False,
        "dry_check_no_http": True,
        "targets": list(selected_targets),
        "seed_mode": mode_s,
        "seed_source": (
            "croatia_seed_targets"
            if mode_s == SEED_MODE_CROATIA_LEGACY
            else "seed_targets_from_story"
        ),
        "causal_json": str(causal_json) if causal_json else None,
        "seed_error": seed_error,
        "seed_windows": seed_windows,
        "seed_policy": {
            "board_is_not_goal_action": True,
            "default_mode": SEED_MODE_STORY,
            "croatia_legacy_explicit_only": True,
            "preflight_run_same_resolver": "resolve_seed_targets",
        },
        "run_profile": {
            "max_rounds": max_rounds,
            "frames_per_round": frames_per_round,
            "frame_budget": frame_budget,
            "max_api_calls_explicit": max_api_calls,
            "max_completion_tokens_explicit": max_completion_tokens,
        },
        "first_real_vlm_only_recommended": dict(FIRST_REAL_VLM_ONLY),
        "effective_caps": {
            "max_calls": caps["max_calls"],
            "max_cost_usd": caps["max_cost_usd"],
            "max_completion_tokens": caps["max_completion_tokens"],
            "sources": caps["sources"],
            "note": "effective = min(code_explicit, env) when both set; cost is estimate only",
            "cost_is_estimate_not_invoice_cap": True,
        },
        "models": {
            "planner": request_models["planner"],
            "vision": request_models["vision"],
        },
        "official_video_rsi_models": dict(OFFICIAL_VIDEO_RSI_MODELS),
        "request_models": request_models,
        "request_model_note": (
            "official labels are Video-RSI dual-model names; "
            "actual request_model must be a vendor-available model id "
            "(STORY_LLM_MODEL / STORY_VLM_MODEL)"
        ),
        "vendor_compat": {
            "token_param": caps["token_param"],
            "planner_token_param": endpoints["planner"].get("token_param"),
            "vision_token_param": endpoints["vision"].get("token_param"),
            "planner_base_url_set": bool(endpoints["planner"].get("base_url")),
            "vision_base_url_set": bool(endpoints["vision"].get("base_url")),
            "planner_api_key_set": bool(endpoints["planner"].get("api_key_set")),
            "vision_api_key_set": bool(endpoints["vision"].get("api_key_set")),
            "planner_timeout_sec": endpoints["planner"].get("timeout_sec"),
            "vision_timeout_sec": endpoints["vision"].get("timeout_sec"),
            "planner_max_retries": endpoints["planner"].get("max_retries"),
            "vision_max_retries": endpoints["vision"].get("max_retries"),
            "sends_both_token_params": False,
            "compat_note": "only one of max_tokens|max_completion_tokens|none is sent",
        },
        "endpoint_ready": {
            "planner_configured": bool(configs["planner"].configured()),
            "vision_configured": bool(configs["vision"].configured()),
            "roles_required": roles,
            "roles_ready": all(configs[r].configured() for r in roles),
        },
        "verify_key_persistent": verify_key_is_persistent(),
        "roles": roles,
        # 明确不回传任何 key 明文
        "secrets_redacted": True,
    }
    if problems and want_real and raise_on_problems:
        raise Phase4AError("; ".join(problems))
    return report


def classify_observation_labels(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """从 VLM 文本抽取视觉标签与不确定性（观察层）。"""
    import re

    # 仅用 observed_actions 抽正向标签，避免 seed/notes 里的 “goal” 字样污染
    actions_blob = " ".join(str(a) for a in (evidence.get("observed_actions") or [])).lower()
    notes_blob = " ".join(
        [
            str(evidence.get("story_relation") or ""),
            str(evidence.get("notes") or ""),
        ]
    ).lower()
    labels: List[str] = []
    positive_mapping = [
        ("goal", (r"\bgoal\b", "进球", "ball in net", "破门")),
        ("shot", (r"\bshot\b", r"\bshoot\b", "射门", "strike")),
        ("score_change", ("score change", "scoreboard change", "比分变化")),
        ("celebration", ("celebrat", "庆祝", "crowd cheer")),
        ("replay", (r"\breplay\b", "回放", "slow motion", "slo-mo")),
        ("scoreboard", ("scoreboard", "scorebug", "记分牌", "比分牌")),
    ]
    soft_mapping = [
        ("unrelated", ("unrelated", "无关", "irrelevant", "no goal", "无进球")),
        ("uncertain", (r"\buncertain\b", "不确定", "不足以")),
    ]

    def _hit(blob: str, keys: tuple) -> bool:
        for k in keys:
            if k.startswith(r"\b"):
                if re.search(k, blob):
                    return True
            elif k in blob:
                return True
        return False

    for lab, keys in positive_mapping:
        if _hit(actions_blob, keys):
            labels.append(lab)
    for lab, keys in soft_mapping:
        if _hit(actions_blob, keys) or _hit(notes_blob, keys):
            labels.append(lab)
    if not labels:
        labels.append("uncertain")
    conf = float(evidence.get("confidence") or 0.0)
    uncertainty = max(0.0, min(1.0, 1.0 - conf))
    if evidence.get("failure_status") or not evidence.get("normalized_ok"):
        uncertainty = max(uncertainty, 0.7)
        if "unrelated" not in labels and "uncertain" not in labels:
            labels.append("uncertain")
    return {
        "labels": labels,
        "primary": labels[0],
        "confidence": conf,
        "uncertainty": uncertainty,
        "frame_ids": list(evidence.get("frame_ids") or []),
        "provider_mode": evidence.get("provider_mode"),
        "description": str(evidence.get("story_relation") or evidence.get("notes") or ""),
        "observation_only": True,
        "fact_verified": False,
    }


def rule_decide_next_window(
    *,
    target: Dict[str, Any],
    window: Dict[str, float],
    labels: Dict[str, Any],
    media: MediaInfo,
    cfg: Phase4AConfig,
    round_idx: int,
) -> Dict[str, Any]:
    """规则规划器：无关→扩展/平移；相关→收窄；预算用尽→停止。"""
    dur = float(media.duration_sec)
    start, end = float(window["start"]), float(window["end"])
    labs = set(labels.get("labels") or [])
    conf = float(labels.get("confidence") or 0.0)
    primary = labels.get("primary")

    decision = {
        "action": "stop",
        "reason": "",
        "next_window": {"start": start, "end": end},
        "planner": "rule",
    }

    positive = labs & {"shot", "goal", "celebration", "score_change"}
    if positive and conf >= 0.45 and "unrelated" not in labs:
        # 收窄到中心附近
        mid = (start + end) / 2.0
        half = max(3.0, (end - start) / 4.0)
        decision.update(
            {
                "action": "shrink",
                "reason": f"positive_labels={sorted(positive)} conf={conf:.2f}",
                "next_window": {
                    "start": max(0.0, mid - half),
                    "end": min(dur, mid + half),
                },
            }
        )
        if round_idx >= 1 and conf >= 0.55:
            decision["action"] = "accept"
            decision["reason"] += "; accept_candidate"
        return decision

    if "unrelated" in labs or conf < 0.2 or primary == "uncertain":
        # 相对比分锚点向前搜索（进球通常早于记分牌）
        score_t = float(target.get("score_anchor_sec") or end)
        shift = float(cfg.shift_sec)
        if target.get("kind") == "action_locate":
            new_end = max(0.5, start - 2.0)
            new_start = max(0.0, new_end - (end - start) - shift)
            decision.update(
                {
                    "action": "shift_earlier",
                    "reason": "weak/unrelated; search earlier before scoreboard",
                    "next_window": {"start": new_start, "end": new_end},
                }
            )
        else:
            expand = float(cfg.expand_sec)
            decision.update(
                {
                    "action": "expand",
                    "reason": "weak/unrelated; expand around seed",
                    "next_window": {
                        "start": max(0.0, start - expand),
                        "end": min(dur, end + expand),
                    },
                }
            )
        return decision

    if "replay" in labs and "goal" not in labs:
        decision.update(
            {
                "action": "shift_earlier",
                "reason": "looks_like_replay; seek live earlier",
                "next_window": {
                    "start": max(0.0, start - cfg.shift_sec),
                    "end": max(0.5, end - cfg.shift_sec / 2.0),
                },
            }
        )
        return decision

    decision["action"] = "continue"
    decision["reason"] = f"ambiguous labels={sorted(labs)}"
    return decision


def _llm_planner_refine(
    api: ApiProvider,
    *,
    target: Dict[str, Any],
    window: Dict[str, float],
    labels: Dict[str, Any],
    media: MediaInfo,
) -> Optional[Dict[str, Any]]:
    """可选 LLM planner；失败则返回 None 由规则接管。"""
    mock_obj = {
        "action": "expand",
        "reason": "mock planner expand",
        "next_window": {
            "start": max(0.0, float(window["start"]) - 6.0),
            "end": min(float(media.duration_sec), float(window["end"]) + 6.0),
        },
    }
    user_prompt = (
        "Return ONE JSON object: "
        '{"action":"expand|shrink|shift_earlier|shift_later|accept|stop",'
        '"reason":"...","next_window":{"start":float,"end":float}}. '
        "Do NOT invent verified facts. Windows must stay within "
        f"[0, {media.duration_sec:.1f}]. "
        f"target={target.get('target_id')} score_anchor={target.get('score_anchor_sec')} "
        f"current_window={window} labels={labels}"
    )
    try:
        raw = api.plan_decision(
            system_prompt=(
                "You plan the next football story video search window. "
                "Reply with strict JSON only. Never mark evidence as verified."
            ),
            user_prompt=user_prompt,
            mock_decision=mock_obj,
        )
    except Exception:  # noqa: BLE001
        return None
    mode = str(raw.get("provider_mode") or raw.get("provider") or "")
    content = str(raw.get("content") or "")
    try:
        obj = json.loads(content) if content.strip().startswith("{") else None
        if obj is None:
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                obj = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "next_window" not in obj:
        return None
    nw = obj.get("next_window") or {}
    try:
        a, b = float(nw["start"]), float(nw["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 <= a < b <= float(media.duration_sec) + 1e-3):
        return None
    return {
        "action": str(obj.get("action") or "continue"),
        "reason": str(obj.get("reason") or "llm_planner"),
        "next_window": {"start": a, "end": b},
        "planner": "llm",
        "provider_mode": mode if mode in ("real", "cache", "mock") else "mock",
    }


def _vision_prompt_extra() -> str:
    return (
        "Classify whether frames show: shot, goal, score_change, celebration, "
        "replay, scoreboard, or unrelated. Put labels into observed_actions. "
        "Express uncertainty in notes. Never claim verified timestamps."
    )


def observe_window(
    *,
    store: FrameStore,
    vision: VisionProvider,
    target: Dict[str, Any],
    window: Dict[str, float],
    frames_per_round: int,
) -> Dict[str, Any]:
    gap_id = str(target["gap_id"])
    try:
        frames = store.extract_window(
            float(window["start"]),
            float(window["end"]),
            gap_id=gap_id,
            tool="phase4a_shot_search",
            count=max(1, frames_per_round),
        )
    except FrameBudgetExhausted as exc:
        return {
            "ok": False,
            "failure_status": "frame_budget_exhausted",
            "message": str(exc),
            "frames": [],
            "evidence": {},
            "labels": {
                "labels": ["uncertain"],
                "primary": "uncertain",
                "confidence": 0.0,
                "uncertainty": 1.0,
                "frame_ids": [],
            },
        }
    if not frames:
        return {
            "ok": False,
            "failure_status": "no_frames",
            "message": "no frames extracted",
            "frames": [],
            "evidence": {},
            "labels": {
                "labels": ["uncertain"],
                "primary": "uncertain",
                "confidence": 0.0,
                "uncertainty": 1.0,
                "frame_ids": [],
            },
        }

    frame_ids = [f.frame_id for f in frames]
    bindings = [f.to_dict() for f in frames]
    paths = [Path(f.path) for f in frames]
    note = (
        f"{target.get('seed_note')}; window={window}; "
        f"score_anchor={target.get('score_anchor_sec')}. {_vision_prompt_extra()}"
    )
    evidence = vision.describe_frames(
        gap_id=gap_id,
        gap_note=note,
        frame_paths=paths,
        frame_ids=frame_ids,
        frame_bindings=bindings,
        gap={
            "kind": target.get("kind"),
            "gap_id": gap_id,
            "score_anchor_sec": target.get("score_anchor_sec"),
        },
    )
    # 剥离模型可能返回的信任字段
    evidence = strip_external_trust_flags(evidence)
    evidence["fact_verified"] = False
    evidence["observation_only"] = True
    if evidence.get("pipeline_verified"):
        evidence["pipeline_verified"] = False
    labels = classify_observation_labels(evidence)
    # 结构化证据条（供 Verifier）
    evidence_row = {
        "gap_id": gap_id,
        "provider_mode": evidence.get("provider_mode"),
        "normalized_ok": bool(evidence.get("normalized_ok")),
        "is_mock": evidence.get("provider_mode") == "mock",
        "frame_ids": labels["frame_ids"],
        "observed_actions": evidence.get("observed_actions"),
        "story_relation": evidence.get("story_relation"),
        "confidence": labels["confidence"],
        "uncertainty": labels["uncertainty"],
        "visual_labels": labels["labels"],
        "notes": evidence.get("notes"),
        "message": evidence.get("message") or evidence.get("notes"),
        "failure_status": evidence.get("failure_status"),
        "conflict": evidence.get("conflict"),
        "window": dict(window),
        "usage": evidence.get("usage"),
        "est_cost_usd": evidence.get("est_cost_usd"),
        "model": evidence.get("model"),
        "observation_only": True,
        "fact_verified": False,
    }
    return {
        "ok": bool(evidence.get("normalized_ok")),
        "failure_status": evidence.get("failure_status"),
        "frames": [f.to_dict() for f in frames],
        "evidence": evidence_row,
        "labels": labels,
        "raw_evidence": evidence,
    }


def search_target(
    *,
    target: Dict[str, Any],
    store: FrameStore,
    vision: VisionProvider,
    api: ApiProvider,
    media: MediaInfo,
    cfg: Phase4AConfig,
) -> Dict[str, Any]:
    """对单一目标多轮搜索。"""
    window = dict(target["window"])
    rounds: List[Dict[str, Any]] = []
    best: Optional[Dict[str, Any]] = None

    for r in range(int(cfg.max_rounds)):
        if store.budget.remaining_for(str(target["gap_id"])) <= 0:
            rounds.append(
                {
                    "round": r,
                    "stop": "frame_budget",
                    "window": window,
                }
            )
            break
        obs = observe_window(
            store=store,
            vision=vision,
            target=target,
            window=window,
            frames_per_round=cfg.frames_per_round,
        )
        decision = rule_decide_next_window(
            target=target,
            window=window,
            labels=obs["labels"],
            media=media,
            cfg=cfg,
            round_idx=r,
        )
        llm_dec = None
        if cfg.mode == "planner-vlm-loop":
            llm_dec = _llm_planner_refine(
                api,
                target=target,
                window=window,
                labels=obs["labels"],
                media=media,
            )
            if llm_dec is not None:
                # LLM 建议与规则合并：优先 LLM 窗口，保留规则 action 作对照
                decision = {
                    **decision,
                    "llm": llm_dec,
                    "action": llm_dec.get("action") or decision["action"],
                    "next_window": llm_dec.get("next_window") or decision["next_window"],
                    "reason": f"rule={decision.get('reason')}; llm={llm_dec.get('reason')}",
                    "planner": "rule+llm",
                }

        round_rec = {
            "round": r,
            "window": dict(window),
            "observation": {
                "ok": obs["ok"],
                "labels": obs["labels"],
                "evidence": obs["evidence"],
                "frame_ids": [f.get("frame_id") for f in obs["frames"]],
                "frame_times": [
                    {
                        "frame_id": f.get("frame_id"),
                        "requested_media_sec": f.get("requested_media_sec"),
                        "actual_media_sec": f.get("actual_media_sec"),
                    }
                    for f in obs["frames"]
                ],
            },
            "decision": decision,
        }
        rounds.append(round_rec)

        # 追踪最佳正向观察
        labs = set((obs["labels"] or {}).get("labels") or [])
        conf = float((obs["labels"] or {}).get("confidence") or 0)
        score = conf + (0.3 if labs & {"goal", "shot", "celebration"} else 0.0)
        score -= 0.5 if "unrelated" in labs else 0.0
        if best is None or score > best.get("_score", -1):
            best = {
                "_score": score,
                "window": dict(window),
                "labels": obs["labels"],
                "evidence": obs["evidence"],
                "round": r,
            }

        action = decision.get("action")
        if action in ("accept", "stop"):
            break
        nxt = decision.get("next_window") or window
        if abs(float(nxt["start"]) - float(window["start"])) < 1e-6 and abs(
            float(nxt["end"]) - float(window["end"])
        ) < 1e-6:
            break
        # 仅当仍有后续 round 时才推进；否则 next_window 保持「待执行」
        if r + 1 >= int(cfg.max_rounds):
            round_rec["next_window_pending"] = {
                "window": {
                    "start": float(nxt["start"]),
                    "end": float(nxt["end"]),
                },
                "applied": False,
                "reason": "max_rounds_reached_before_next_observe",
            }
            break
        window = {
            "start": float(nxt["start"]),
            "end": float(nxt["end"]),
        }

    best_clean = {k: v for k, v in (best or {}).items() if k != "_score"}
    last_decision = (rounds[-1].get("decision") if rounds else None) or {}
    pending = (rounds[-1].get("next_window_pending") if rounds else None) or {}
    return {
        "target_id": target["target_id"],
        "role": target["role"],
        "gap_id": target["gap_id"],
        "seed_center_sec": target.get("seed_center_sec"),
        "score_anchor_sec": target.get("score_anchor_sec"),
        "seed_window": dict(target["window"]),
        "rounds": rounds,
        "best": best_clean,
        "n_rounds": len(rounds),
        "window_provenance": {
            "observed_best_window": best_clean.get("window"),
            "proposed_next_window": (last_decision.get("next_window") if last_decision else None),
            "proposed_next_action": last_decision.get("action"),
            "next_window_applied": bool(pending.get("applied")) if pending else False,
            "next_window_pending": pending or None,
            "note": (
                "EDL/candidate writes observed_best_window only; "
                "proposed_next_window is a plan for a subsequent round and is NOT "
                "verified localization by itself"
            ),
        },
    }


def _segment_for_target(plan: Dict[str, Any], target: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    hints = list(target.get("segment_id_hints") or [])
    for sid in hints:
        for seg in plan.get("segments") or []:
            if seg.get("segment_id") == sid:
                return seg
    role = target.get("role")
    for seg in plan.get("segments") or []:
        if seg.get("role") == role:
            return seg
    return None


def apply_search_to_plan(
    plan: Dict[str, Any],
    searches: Sequence[Dict[str, Any]],
    *,
    cfg: Phase4AConfig,
    visual_evidence: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """回填观察与候选窗；禁止模型 verified 提权。"""
    plan = sanitize_plan_trust(copy.deepcopy(plan))
    visual_evidence = list(visual_evidence or [])
    updates: List[Dict[str, Any]] = []

    for search in searches:
        target_id = search["target_id"]
        best = search.get("best") or {}
        labels = best.get("labels") or {}
        evidence = best.get("evidence") or {}
        win = best.get("window") or search.get("seed_window")
        provider_mode = labels.get("provider_mode") or evidence.get("provider_mode")
        labs = set(labels.get("labels") or [])
        conf = float(labels.get("confidence") or 0.0)
        positive = bool(labs & {"shot", "goal", "celebration", "score_change"}) and conf >= 0.35

        # 定位 segment
        # reconstruct a minimal target dict for lookup
        target = {
            "role": search.get("role"),
            "segment_id_hints": [
                f"seg_{search['role']}" if search.get("role") else "",
                "seg_go_ahead_goal_pending"
                if search.get("target_id") == "go_ahead_goal"
                else "seg_equalizer_goal_action",
            ],
        }
        seg = _segment_for_target(plan, target)
        if seg is None and search.get("role"):
            # 创建缺失的 go_ahead goal 候选段
            if search["target_id"] == "go_ahead_goal" and positive and win:
                from story_video_agent.narrative_composer import _mk_seg

                seg = _mk_seg(
                    segment_id="seg_go_ahead_goal_action",
                    beat="高潮",
                    role="go_ahead_goal_action",
                    event_ids=[],
                    frame_ids=list(labels.get("frame_ids") or []),
                    evidence_refs=[],
                    media_in=round(float(win["start"]), 3),
                    media_out=round(float(win["end"]), 3),
                    time_status="pending_review",
                    shot_kind="live",
                    is_replay=False,
                    narration="Phase4A 候选 go_ahead 进球窗（待内部核验）。",
                    selection_reason="phase4a_vlm_candidate",
                    source_refs=[],
                    confidence=conf,
                    time_provenance={
                        "source": "phase4a_search",
                        "pipeline_verified": False,
                        "granted_by": None,
                        "seed_center_sec": search.get("seed_center_sec"),
                    },
                    render_eligibility="candidate_only",
                    blocking_reasons=["awaiting_internal_media_verification", "phase4a_pending_review"],
                )
                # insert before ending if possible
                segs = plan.get("segments") or []
                insert_at = len(segs)
                for i, s in enumerate(segs):
                    if s.get("role") == "ending" or s.get("segment_id") == "seg_ending":
                        insert_at = i
                        break
                segs.insert(insert_at, seg)
                # remove pure pending placeholder if present
                plan["segments"] = [
                    s
                    for s in segs
                    if s.get("segment_id") != "seg_go_ahead_goal_pending"
                ]
                seg = next(
                    s
                    for s in plan["segments"]
                    if s.get("segment_id") == "seg_go_ahead_goal_action"
                )

        orig_in = seg.get("media_in") if seg else None
        orig_out = seg.get("media_out") if seg else None
        adjusted = False
        allow_adjust = provider_mode == "real" or (
            provider_mode == "mock" and cfg.allow_mock_window_adjust
        )

        if seg is not None and positive and win and allow_adjust:
            new_in = round(float(win["start"]), 3)
            new_out = round(float(win["end"]), 3)
            if new_in < new_out:
                seg["media_in"] = new_in
                seg["media_out"] = new_out
                seg["source_media_order"] = new_in
                if seg.get("time_status") in (
                    None,
                    "pending_localization",
                    "unavailable",
                ):
                    seg["time_status"] = "pending_review"
                elif seg.get("time_status") == "pending_localization":
                    seg["time_status"] = "pending_review"
                if seg.get("render_eligibility") == "blocked":
                    seg["render_eligibility"] = "candidate_only"
                br = [
                    b
                    for b in (seg.get("blocking_reasons") or [])
                    if b not in ("missing_trusted_goal_action:go_ahead",)
                ]
                if "awaiting_internal_media_verification" not in br:
                    br.append("awaiting_internal_media_verification")
                if "phase4a_observation_unverified" not in br:
                    br.append("phase4a_observation_unverified")
                seg["blocking_reasons"] = br
                # 绝不写入 granted_by / pipeline_verified True
                prov = dict(seg.get("time_provenance") or {})
                prov["pipeline_verified"] = False
                prov["granted_by"] = None
                prov["phase4a"] = {
                    "adjusted": True,
                    "provider_mode": provider_mode,
                    "labels": list(labs),
                    "confidence": conf,
                }
                seg["time_provenance"] = prov
                fids = list(labels.get("frame_ids") or [])
                if fids:
                    seg["frame_ids"] = sorted(set(list(seg.get("frame_ids") or []) + fids))
                adjusted = True

        if evidence:
            visual_evidence.append(evidence)
            # classify for evidence_refs style
            cl = classify_visual_evidence(evidence)
            # force non-verified
            cl["kind"] = "mock" if provider_mode == "mock" else "vlm_observation"
            cl["used_as_fact"] = False
            cl["pipeline_verified"] = False
            cl["phase4a_target"] = target_id
            plan.setdefault("evidence_refs", []).append(cl)

        provenance = search.get("window_provenance") or {}
        updates.append(
            {
                "target_id": target_id,
                "segment_id": seg.get("segment_id") if seg else None,
                "original_media_in": orig_in,
                "original_media_out": orig_out,
                "adjusted_media_in": seg.get("media_in") if seg else None,
                "adjusted_media_out": seg.get("media_out") if seg else None,
                "window_adjusted": adjusted,
                "observed_window_written": dict(win) if win else None,
                "proposed_next_window": provenance.get("proposed_next_window"),
                "next_window_applied": bool(provenance.get("next_window_applied")),
                "labels": labels,
                "provider_mode": provider_mode,
                "verification_status": "observation_only",
                "not_fine_localized": (
                    bool(provenance.get("proposed_next_window"))
                    and not bool(provenance.get("next_window_applied"))
                ),
            }
        )

    # 重建 narrative_order / EDL
    for i, seg in enumerate(plan.get("segments") or []):
        seg["narrative_order"] = i + 1
        if seg.get("media_in") is not None:
            seg["source_media_order"] = seg.get("media_in")
    plan["candidate_edl"] = build_candidate_edl(plan.get("segments") or [])
    plan["render_ready_edl"] = build_render_ready_edl(plan.get("segments") or [])
    plan["edl"] = plan["candidate_edl"]
    plan["render_ready"] = False  # Phase 4A 默认不成片
    plan.setdefault("diagnostics", {})
    plan["diagnostics"]["phase4a"] = {
        "updates": updates,
        "visual_evidence_count": len(visual_evidence),
        "granted_by_authority": GRANTED_BY,
        "note": "VLM observations never grant render_ready",
    }
    ok, problems = validate_compose_plan(plan)
    plan["structure_ok"] = ok
    plan["diagnostics"]["structure_problems"] = problems
    return plan


def compare_plans(v1: Dict[str, Any], v2: Dict[str, Any]) -> Dict[str, Any]:
    def _seg_map(p: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {s["segment_id"]: s for s in (p.get("segments") or []) if s.get("segment_id")}

    m1, m2 = _seg_map(v1), _seg_map(v2)
    moved = []
    for sid, s2 in m2.items():
        s1 = m1.get(sid)
        if not s1:
            moved.append({"segment_id": sid, "change": "added", "v2": [s2.get("media_in"), s2.get("media_out")]})
            continue
        if s1.get("media_in") != s2.get("media_in") or s1.get("media_out") != s2.get("media_out"):
            moved.append(
                {
                    "segment_id": sid,
                    "change": "window_moved",
                    "v1": [s1.get("media_in"), s1.get("media_out")],
                    "v2": [s2.get("media_in"), s2.get("media_out")],
                    "role": s2.get("role"),
                }
            )
    missing_v1 = sum(
        1
        for s in (v1.get("segments") or [])
        if s.get("media_in") is None or s.get("render_eligibility") == "blocked"
    )
    missing_v2 = sum(
        1
        for s in (v2.get("segments") or [])
        if s.get("media_in") is None or s.get("render_eligibility") == "blocked"
    )
    goals_located = [
        u
        for u in ((v2.get("diagnostics") or {}).get("phase4a") or {}).get("updates") or []
        if u.get("window_adjusted") and "goal" in str(u.get("target_id"))
    ]
    return {
        "n_segments_v1": len(v1.get("segments") or []),
        "n_segments_v2": len(v2.get("segments") or []),
        "n_candidate_edl_v1": len(v1.get("candidate_edl") or []),
        "n_candidate_edl_v2": len(v2.get("candidate_edl") or []),
        "missing_or_blocked_v1": missing_v1,
        "missing_or_blocked_v2": missing_v2,
        "windows_changed": moved,
        "goals_adjusted": goals_located,
        "render_ready_v1": bool(v1.get("render_ready")),
        "render_ready_v2": bool(v2.get("render_ready")),
        "story_completeness_delta": missing_v1 - missing_v2,
    }


def run_phase4a(
    *,
    story_json: PathLike,
    video_path: PathLike,
    plan_json: Optional[PathLike] = None,
    out_dir: PathLike,
    cfg: Optional[Phase4AConfig] = None,
    render_preview: bool = True,
    v1_preview_summary: Optional[PathLike] = None,
    causal_json: Optional[PathLike] = None,
    seed_mode: str = SEED_MODE_STORY,
) -> Dict[str, Any]:
    cfg = cfg or Phase4AConfig()
    story_json = Path(story_json)
    video_path = Path(video_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    causal_path = Path(causal_json) if causal_json else None
    mode_s = (seed_mode or SEED_MODE_STORY).strip().lower()

    # 门控：若用户未显式要求 real，强制 mock
    if not cfg.force_mock and not billing_allowed():
        raise Phase4AError(
            "Real Phase 4A refused: set STORY_API_ENABLE=1 STORY_PHASE4A_REAL=1 "
            "STORY_API_SMOKE=1 plus keys/caps, or use force_mock=True"
        )

    pf = preflight_phase4a(
        mode=cfg.mode,
        story_json=story_json,
        video_path=video_path,
        force_mock=cfg.force_mock,
        max_api_calls=cfg.max_api_calls,
        targets=cfg.targets,
        max_rounds=cfg.max_rounds,
        frames_per_round=cfg.frames_per_round,
        frame_budget=cfg.frame_budget,
        causal_json=causal_path,
        seed_mode=mode_s,
        window_half_sec=cfg.window_half_sec,
    )

    story = json.loads(story_json.read_text(encoding="utf-8"))
    causal_obj: Optional[Dict[str, Any]] = None
    if causal_path is not None:
        causal_obj = load_optional_json(causal_path)
    if plan_json and Path(plan_json).is_file():
        plan_v1 = json.loads(Path(plan_json).read_text(encoding="utf-8"))
    else:
        plan_v1 = compose_story_plan(story, use_llm=False)

    media = probe_video(video_path)
    try:
        # 必须与 preflight 同一 resolve_seed_targets
        targets = resolve_seed_targets(
            cfg.targets,
            half=cfg.window_half_sec,
            story=story if isinstance(story, dict) else None,
            causal=causal_obj,
            seed_mode=mode_s,
        )
    except ValueError as exc:
        raise Phase4AError(str(exc)) from exc
    # 审计：run 种子与 preflight 一致
    pf_seeds = [
        (w.get("target_id"), w.get("seed_center_sec"), w.get("score_anchor_sec"))
        for w in (pf.get("seed_windows") or [])
    ]
    run_seeds = [
        (t.get("target_id"), t.get("seed_center_sec"), t.get("score_anchor_sec"))
        for t in targets
    ]
    if pf_seeds != run_seeds:
        raise Phase4AError(
            f"preflight/run seed mismatch: preflight={pf_seeds} run={run_seeds}"
        )

    gap_ids = [t["gap_id"] for t in targets]
    caps = allocate_gap_caps(gap_ids, global_budget=cfg.frame_budget)
    frame_dir = out_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    store = FrameStore(
        media,
        out_dir=frame_dir,
        budget=FrameBudget(max_frames=cfg.frame_budget, per_gap_caps=caps),
    )

    # max_calls：代码配置与 STORY_API_MAX_CALLS 取更严（ApiProvider 内合并）
    api = ApiProvider(
        force_mock=cfg.force_mock,
        require_real=not cfg.force_mock,
        required_roles=["vision"] if cfg.mode == "vlm-only" else ["vision", "planner"],
        max_calls=cfg.max_api_calls,
    )
    # 记录真正生效的限额，便于审计
    pf["api_status_caps"] = {
        "max_calls": api.max_calls,
        "max_cost_usd": api.max_cost_usd,
        "max_completion_tokens": api.max_completion_tokens,
        "cap_sources": api.cap_sources,
    }
    vision = VisionProvider(api, force_mock=cfg.force_mock)

    t0 = time.perf_counter()
    searches: List[Dict[str, Any]] = []
    for target in targets:
        searches.append(
            search_target(
                target=target,
                store=store,
                vision=vision,
                api=api,
                media=media,
                cfg=cfg,
            )
        )

    plan_v2 = apply_search_to_plan(plan_v1, searches, cfg=cfg)
    # Verifier 回填
    vis_rows = []
    for s in searches:
        ev = (s.get("best") or {}).get("evidence")
        if ev:
            vis_rows.append(ev)
    vrep = verify_story(story, visual_evidence=vis_rows)
    plan_v2.setdefault("diagnostics", {})["story_verifier"] = {
        "conflicts": vrep.get("conflicts"),
        "notes": "phase4a visual evidence classified; none used as fact unless internal grant",
    }

    # 内部时间核验（默认不 promote）
    plan_v2 = apply_internal_verification(
        plan_v2,
        media,
        promote_to_render_ready=bool(cfg.promote_to_render_ready),
    )

    plan_path = out_dir / "croatia_plan_phase4a.json"
    plan_path.write_text(json.dumps(plan_v2, ensure_ascii=False, indent=2), encoding="utf-8")
    edl_path = out_dir / "croatia_candidate_edl_phase4a.json"
    edl_path.write_text(
        json.dumps(plan_v2.get("candidate_edl") or [], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    comparison = compare_plans(plan_v1, plan_v2)
    render_result = None
    review = None
    if render_preview:
        mp4 = out_dir / "croatia_preview_v2.mp4"
        try:
            render_result = render_story_video(
                plan_v2,
                video_path,
                mp4,
                mode="preview",
                work_dir=out_dir / "work_preview_v2",
                max_clip_sec=3.0,
            )
            review = build_review_manifest(
                plan_v2, video_path, out_dir / "review_v2", max_segments=8
            )
        except RenderError as exc:
            render_result = {"ok": False, "error": str(exc)}

    usage = api.stats.summary()
    elapsed = round(time.perf_counter() - t0, 4)

    # v1 summary if provided
    v1_meta = None
    if v1_preview_summary and Path(v1_preview_summary).is_file():
        v1_meta = json.loads(Path(v1_preview_summary).read_text(encoding="utf-8"))

    report = {
        "phase": "4A",
        "preflight": pf,
        "config": cfg.to_dict(),
        "real_api_executed": (not cfg.force_mock) and api.status().get("mode") == "real",
        "api_mode": api.status().get("mode"),
        "cost_disclaimer": COST_DISCLAIMER,
        "elapsed_sec": elapsed,
        "api_usage": usage,
        "http_attempts": usage.get("http_attempts"),
        "est_cost_usd_real": usage.get("est_cost_usd_real"),
        "frame_budget": {
            "max": store.budget.max_frames,
            "used": store.budget.used,
            "per_gap_used": dict(store.budget.per_gap_used),
        },
        "searches": searches,
        "comparison": comparison,
        "v1_preview": v1_meta,
        "v2_preview": {
            "out_mp4": (render_result or {}).get("out_mp4"),
            "n_cut": (render_result or {}).get("n_cut"),
            "n_placeholder": (render_result or {}).get("n_placeholder"),
            "output_media": (render_result or {}).get("output_media"),
            "error": (render_result or {}).get("error"),
        },
        "review_manifest": (review or {}).get("path"),
        "contact_sheet": (review or {}).get("contact_sheet"),
        "plan_v2_path": str(plan_path),
        "candidate_edl_v2_path": str(edl_path),
        "paths": {
            "out_dir": str(out_dir.resolve()),
            "frames": str(frame_dir.resolve()),
        },
    }
    report_path = out_dir / "phase4a_experiment_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path.resolve())
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 4A shot optimize (gated real API)")
    parser.add_argument("--story-json", type=Path, required=True)
    parser.add_argument("--video-path", type=Path, required=True)
    parser.add_argument(
        "--causal-json",
        type=Path,
        default=None,
        help="Optional causal JSON for story-driven seed targets",
    )
    parser.add_argument(
        "--seed-mode",
        choices=list(SEED_MODES),
        default=SEED_MODE_STORY,
        help=(
            "story (default): seed_targets_from_story; "
            "croatia_legacy: hardcoded Croatia seeds for explicit compat tests only"
        ),
    )
    parser.add_argument("--plan-json", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=EXPERIMENT_MODES,
        default="vlm-only",
        help="vlm-only | planner-vlm-loop",
    )
    parser.add_argument(
        "--targets",
        nargs="+",
        default=None,
        metavar="TARGET",
        help=(
            "Search targets: equalizer_goal and/or go_ahead_goal "
            "(space or comma separated). Default: both (backward compatible)."
        ),
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="Request real API (still requires STORY_PHASE4A_REAL=1 etc.)",
    )
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--frame-budget", type=int, default=18)
    parser.add_argument("--frames-per-round", type=int, default=3)
    parser.add_argument(
        "--max-api-calls",
        type=int,
        default=None,
        help="Explicit HTTP attempt cap (min'd with STORY_API_MAX_CALLS)",
    )
    parser.add_argument(
        "--max-completion-tokens",
        type=int,
        default=None,
        help="Explicit completion token cap (min'd with env)",
    )
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--v1-summary", type=Path, default=None)
    parser.add_argument(
        "--dry-check",
        action="store_true",
        help="Print effective caps/models/compat; never send HTTP",
    )
    args = parser.parse_args(argv)

    try:
        target_ids = parse_targets(args.targets)
    except ValueError as exc:
        print(f"REFUSE: {exc}", file=sys.stderr)
        return 2

    force_mock = not args.real
    # dry-check 允许 --real 仅做配置预检，绝不发 HTTP；真正运行才硬拒绝未授权
    if args.real and not args.dry_check and not billing_allowed():
        print(
            "REFUSE real: need STORY_API_ENABLE=1 STORY_PHASE4A_REAL=1 "
            "STORY_API_SMOKE=1 and keys/caps",
            file=sys.stderr,
        )
        return 2

    max_api_calls = args.max_api_calls
    if max_api_calls is None:
        max_api_calls = Phase4AConfig().max_api_calls

    cfg = Phase4AConfig(
        mode=args.mode,
        force_mock=force_mock,
        max_rounds=args.max_rounds,
        frame_budget=args.frame_budget,
        frames_per_round=args.frames_per_round,
        max_api_calls=max_api_calls,
        targets=target_ids,
    )

    try:
        if args.dry_check:
            pf = preflight_phase4a(
                mode=cfg.mode,
                story_json=args.story_json,
                video_path=args.video_path,
                force_mock=cfg.force_mock,
                max_api_calls=cfg.max_api_calls,
                max_completion_tokens=args.max_completion_tokens,
                targets=cfg.targets,
                max_rounds=cfg.max_rounds,
                frames_per_round=cfg.frames_per_round,
                frame_budget=cfg.frame_budget,
                raise_on_problems=False,
                causal_json=args.causal_json,
                seed_mode=args.seed_mode,
                window_half_sec=cfg.window_half_sec,
            )
            out = {
                "dry_check": True,
                "http_requests_sent": False,
                **pf,
            }
            print(json.dumps(out, ensure_ascii=False, indent=2))
            # 真实模式预检：配置不齐返回非 0，但仍已输出完整报告且未发 HTTP
            if args.real and not pf.get("ok"):
                return 4
            return 0
        report = run_phase4a(
            story_json=args.story_json,
            video_path=args.video_path,
            plan_json=args.plan_json,
            out_dir=args.out_dir,
            cfg=cfg,
            render_preview=not args.no_render,
            v1_preview_summary=args.v1_summary,
            causal_json=args.causal_json,
            seed_mode=args.seed_mode,
        )
    except (Phase4AError, ApiConfigError) as exc:
        print(f"REFUSE: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({
        "ok": True,
        "targets": list(cfg.targets),
        "real_api_executed": report.get("real_api_executed"),
        "api_mode": report.get("api_mode"),
        "elapsed_sec": report.get("elapsed_sec"),
        "comparison": report.get("comparison"),
        "v2_preview": report.get("v2_preview"),
        "report_path": report.get("report_path"),
        "http_attempts": report.get("http_attempts"),
        "est_cost_usd_real": report.get("est_cost_usd_real"),
        "cost_disclaimer": report.get("cost_disclaimer"),
    }, ensure_ascii=False, indent=2))
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
