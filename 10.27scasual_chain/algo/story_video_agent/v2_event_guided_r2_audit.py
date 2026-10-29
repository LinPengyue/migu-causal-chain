"""Round 2 offline audit of Round 1 Event-Guided run (does not overwrite R1 artifacts)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.v2_event_guided_eval import _iou, _overlap


def _center(w: Tuple[float, float]) -> float:
    return 0.5 * (w[0] + w[1])


def load_v1_reference_nodes(story_graph_path: Path, edl_path: Optional[Path] = None) -> Dict[str, Any]:
    """Split V1 story_graph nodes into goal-action vs prelude; mark weak refs."""
    sg = json.loads(Path(story_graph_path).read_text(encoding="utf-8"))
    edl_by_role: Dict[str, Any] = {}
    if edl_path and Path(edl_path).is_file():
        edl = json.loads(Path(edl_path).read_text(encoding="utf-8"))
        for seg in edl if isinstance(edl, list) else (edl.get("segments") or edl.get("edl") or []):
            if isinstance(seg, dict) and seg.get("role"):
                edl_by_role[str(seg["role"])] = seg

    goal_actions: List[Dict[str, Any]] = []
    prelude: List[Dict[str, Any]] = []
    for n in sg.get("nodes") or []:
        role = str(n.get("role") or "")
        mi, mo = n.get("media_in"), n.get("media_out")
        if mi is None or mo is None:
            continue
        edl = edl_by_role.get(role) or {}
        prov = edl.get("time_provenance") or {}
        pipeline_verified = bool(prov.get("pipeline_verified"))
        human_confirmed = bool(edl.get("human_confirmed") or prov.get("human_confirmed"))
        # V1 Croatia refs are pipeline_verified=false → weak reference
        strength = "strict_gold" if (human_confirmed or pipeline_verified) else "weak_reference"
        row = {
            "id": n.get("id"),
            "role": role,
            "media_start_sec": float(mi),
            "media_end_sec": float(mo),
            "shot_kind": n.get("shot_kind"),
            "event_id": n.get("event_id"),
            "pipeline_verified": pipeline_verified,
            "human_confirmed": human_confirmed,
            "reference_strength": strength,
            "edl_provenance_source": prov.get("source"),
            "notes": edl.get("narration") or n.get("narration"),
        }
        if "approach" in role or "prelude" in role or "setup" in role:
            row["category"] = "prelude_before_goal"
            prelude.append(row)
        elif "goal_action" in role:
            row["category"] = "goal_action"
            goal_actions.append(row)

    strict_gold = [g for g in goal_actions if g["reference_strength"] == "strict_gold"]
    weak_refs = [g for g in goal_actions if g["reference_strength"] == "weak_reference"]
    return {
        "schema": "v2_r2_v1_reference_split_v1",
        "n_goal_action_nodes": len(goal_actions),
        "n_prelude_nodes": len(prelude),
        "strict_action_gold": strict_gold,
        "weak_action_references": weak_refs,
        "prelude_references": prelude,
        "note": (
            "Strict action Gold excludes weak/unconfirmed V1 windows and prelude nodes. "
            "Croatia V1 phase5 refs are typically pipeline_verified=false."
        ),
    }


def _pred_windows_from_r1_evidence(evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    preds = []
    for v in evidence.get("verifications") or []:
        s, e = v.get("media_start_sec"), v.get("media_end_sec")
        if s is None or e is None:
            continue
        grade = (v.get("grade") or {}).get("grade") if isinstance(v.get("grade"), dict) else None
        live = (v.get("grade") or {}).get("live_or_replay") if isinstance(v.get("grade"), dict) else None
        perc = v.get("perception") or {}
        preds.append(
            {
                "task_id": v.get("task_id"),
                "tool": v.get("tool"),
                "window": (float(s), float(e)),
                "grade_keyword": grade,
                "live_or_replay_keyword": live,
                "observed_actions": list(perc.get("observed_actions") or []),
                "notes": str(perc.get("notes") or ""),
                "has_frame_cite": bool(
                    re.search(r"\bf_\d+|frame\s*f_?\d+", str(perc.get("notes") or ""), re.I)
                    or any(re.search(r"\bf_\d+", str(a), re.I) for a in (perc.get("observed_actions") or []))
                ),
            }
        )
    return preds


def _best_match(
    gold_w: Tuple[float, float], preds: Sequence[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    gmid = _center(gold_w)
    best = None
    best_key = None
    for p in preds:
        iou = _iou(p["window"], gold_w)
        dist = abs(_center(p["window"]) - gmid)
        key = (dist, -iou)
        if best_key is None or key < best_key:
            best_key = key
            best = {
                "pred": p,
                "iou": iou,
                "center_error_sec": dist,
                "overlap_sec": _overlap(p["window"], gold_w),
            }
    return best


def evaluate_localization_against_refs(
    *,
    preds: Sequence[Dict[str, Any]],
    refs: Sequence[Dict[str, Any]],
    strict_center_sec: float = 5.0,
    strict_iou: float = 0.25,
    loose_center_sec: float = 45.0,
    loose_iou: float = 0.10,
) -> Dict[str, Any]:
    """Strict vs loose localization — does NOT use ±90s as action_recall."""
    rows = []
    strict_hits = 0
    loose_hits = 0
    for g in refs:
        gw = (float(g["media_start_sec"]), float(g["media_end_sec"]))
        m = _best_match(gw, preds)
        if not m:
            row = {
                "ref_id": g.get("id"),
                "role": g.get("role"),
                "category": g.get("category"),
                "reference_strength": g.get("reference_strength"),
                "gold_window": list(gw),
                "matched_strict": False,
                "matched_loose": False,
                "center_error_sec": None,
                "iou": 0.0,
            }
            rows.append(row)
            continue
        p = m["pred"]
        strict = m["center_error_sec"] <= strict_center_sec or m["iou"] >= strict_iou
        loose = m["center_error_sec"] <= loose_center_sec or m["iou"] >= loose_iou
        # Completeness heuristic from notes/actions (audit only)
        blob = (p.get("notes") or "") + " " + " ".join(p.get("observed_actions") or [])
        has_shot = bool(re.search(r"shoot|shot|射门|strikes?", blob, re.I))
        has_net = bool(re.search(r"net|into the goal|入网|破门|ball enters", blob, re.I))
        has_celeb_only = bool(re.search(r"celebrat|庆祝|knee slide|hug", blob, re.I)) and not has_shot
        completeness = "unknown"
        if has_shot and has_net:
            completeness = "shot_and_result_mentioned"
        elif has_celeb_only:
            completeness = "celebration_only_incomplete"
        elif has_shot:
            completeness = "shot_without_clear_result"
        live_ok = None
        if g.get("shot_kind") == "live":
            live_ok = p.get("live_or_replay_keyword") in ("live", "unknown")  # unknown ≠ fail audit
        if strict:
            strict_hits += 1
        if loose:
            loose_hits += 1
        rows.append(
            {
                "ref_id": g.get("id"),
                "role": g.get("role"),
                "category": g.get("category"),
                "reference_strength": g.get("reference_strength"),
                "gold_window": list(gw),
                "pred_task_id": p.get("task_id"),
                "pred_window": list(p["window"]),
                "pred_grade_keyword": p.get("grade_keyword"),
                "center_error_sec": round(m["center_error_sec"], 3),
                "iou": round(m["iou"], 4),
                "matched_strict": strict,
                "matched_loose": loose,
                "live_or_replay_pred": p.get("live_or_replay_keyword"),
                "live_plausible_vs_ref": live_ok,
                "action_completeness_audit": completeness,
                "has_frame_cite": p.get("has_frame_cite"),
                "keyword_grade_inflated_risk": (
                    p.get("grade_keyword") in ("action_localized", "action_corroborated")
                    and completeness in ("celebration_only_incomplete", "unknown")
                    and not p.get("has_frame_cite")
                ),
            }
        )
    n = len(refs) or None
    return {
        "schema": "v2_r2_action_localization_eval_v1",
        "thresholds": {
            "strict_center_sec": strict_center_sec,
            "strict_iou": strict_iou,
            "loose_center_sec": loose_center_sec,
            "loose_iou": loose_iou,
            "note": "±90s is NOT used as action_recall",
        },
        "n_refs": len(refs),
        "strict_localization_recall": (strict_hits / n) if n else None,
        "loose_candidate_recall": (loose_hits / n) if n else None,
        "n_strict_hits": strict_hits,
        "n_loose_hits": loose_hits,
        "rows": rows,
    }


def audit_round1_run(
    *,
    r1_dir: Path,
    story_graph_path: Path,
    edl_path: Optional[Path] = None,
    out_dir: Path,
) -> Dict[str, Any]:
    """Produce round2_audit.json + action_localization_eval.json without touching R1."""
    r1_dir = Path(r1_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    discovery = json.loads((r1_dir / "story_discovery.json").read_text(encoding="utf-8"))
    evidence = json.loads((r1_dir / "story_evidence.json").read_text(encoding="utf-8"))
    trace = json.loads((r1_dir / "agent_trace.json").read_text(encoding="utf-8"))
    offline = json.loads((r1_dir / "offline_eval.json").read_text(encoding="utf-8"))
    candidates = json.loads((r1_dir / "event_candidates.json").read_text(encoding="utf-8"))

    refs = load_v1_reference_nodes(story_graph_path, edl_path)
    preds = _pred_windows_from_r1_evidence(evidence)

    # Planner autonomy: how often DeepSeek chose mid-loop tools
    modes = list(trace.get("planner_mode_log") or [])
    llm_mid = sum(1 for m in modes if m in ("llm", "llm_api"))
    rule_mid = sum(1 for m in modes if str(m).startswith("rule"))
    llm_terminal = sum(1 for m in modes if "terminal" in str(m) or m == "llm_terminal")

    weak_eval = evaluate_localization_against_refs(
        preds=preds, refs=refs["weak_action_references"]
    )
    prelude_eval = evaluate_localization_against_refs(
        preds=preds, refs=refs["prelude_references"], loose_center_sec=60.0
    )
    strict_gold_eval = evaluate_localization_against_refs(
        preds=preds, refs=refs["strict_action_gold"]
    )

    # Relation audit: causal without evidence
    rel_issues = []
    for r in discovery.get("relations") or []:
        kind = r.get("kind") or r.get("relation_type")
        if kind == "causal" and not r.get("supporting_evidence_ids"):
            rel_issues.append(
                {
                    "relation": r,
                    "issue": "causal_without_supporting_evidence_ids",
                    "likely_score_order_fiction": True,
                }
            )

    # Keyword grade inflation samples
    inflated = [
        row
        for row in weak_eval["rows"]
        if row.get("keyword_grade_inflated_risk") or row.get("action_completeness_audit")
        == "celebration_only_incomplete"
    ]

    r1_claimed_recall = (offline.get("action_eval") or {}).get("recall")
    audit = {
        "schema": "v2_event_guided_round2_audit_v1",
        "r1_dir": str(r1_dir),
        "r1_claimed_action_recall_90s": r1_claimed_recall,
        "r1_claimed_recall_invalid_as_action_proof": True,
        "v1_reference_split": {
            "n_goal_actions": refs["n_goal_action_nodes"],
            "n_prelude": refs["n_prelude_nodes"],
            "n_strict_gold": len(refs["strict_action_gold"]),
            "n_weak_refs": len(refs["weak_action_references"]),
            "strict_gold_empty_reason": (
                None
                if refs["strict_action_gold"]
                else "all_v1_goal_action_windows_pipeline_verified_false_or_unconfirmed"
            ),
        },
        "planner_autonomy_audit": {
            "planner_mode_log": modes,
            "n_rule_steps": rule_mid,
            "n_llm_mid_loop": llm_mid,
            "n_llm_terminalish": llm_terminal,
            "event_candidates_used_by_planner": False,
            "finding": (
                "Round1 DeepSeek mostly terminal synthesis; mid-loop search was rule-driven "
                "fixed offsets. event_candidates.json existed but did not drive decisions."
            ),
        },
        "strict_action_gold_eval": strict_gold_eval,
        "weak_reference_eval": weak_eval,
        "prelude_eval": prelude_eval,
        "relation_audit": {
            "n_relations": len(discovery.get("relations") or []),
            "unsupported_causal": rel_issues,
            "finding": (
                "At least one causal edge lacks supporting_evidence_ids; "
                "score-order equalizer→go_ahead is not sufficient for causal."
            ),
        },
        "keyword_grading_risks": inflated,
        "n_event_candidates_file": len(candidates.get("candidates") or []),
        "frames_dir_exists": (r1_dir / "frames_eg").is_dir(),
        "n_saved_frames": len(list((r1_dir / "frames_eg").glob("*.jpg")))
        if (r1_dir / "frames_eg").is_dir()
        else 0,
        "render_ready": False,
    }

    action_eval_out = {
        "schema": "v2_r2_action_localization_eval_bundle_v1",
        "strict_action_gold": strict_gold_eval,
        "weak_reference_goals": weak_eval,
        "prelude_before_goal": prelude_eval,
        "policy": {
            "do_not_use_pm90s_as_action_recall": True,
            "strict_gold_excludes_weak_and_prelude": True,
        },
        "render_ready": False,
    }

    (out_dir / "round2_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "action_localization_eval.json").write_text(
        json.dumps(action_eval_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # Keep a copy of reference split for human review
    (out_dir / "v1_reference_split.json").write_text(
        json.dumps(refs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"audit": audit, "action_eval": action_eval_out, "refs": refs, "out_dir": str(out_dir)}
