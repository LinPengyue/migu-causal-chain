"""G0 isolation helpers — no production side effects, no render_ready upgrade.

Synthetic checks only: cache binding, gold/causal refusal patterns, variable T01
goal counts, and no_comeback / right-side protagonist skeletons.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


FORBIDDEN_INPUT_BASENAMES = (
    "strip_gold.json",
    "highlight_gold.json",
    "highlight_gold_no_t2.json",
    "highlight_gold_with_t2.json",
)
FORBIDDEN_NAME_SUFFIXES = ("_causal.json",)
FORBIDDEN_TOP_KEYS = (
    "causal_chains",
    "causal",
    "story_graph",
    "story_plan",
    "story_roles",
    "strip_gold",
)


def sha256_file(path: Path, *, limit: Optional[int] = None) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        if limit is None:
            while True:
                b = f.read(1024 * 1024)
                if not b:
                    break
                h.update(b)
        else:
            h.update(f.read(limit))
    return h.hexdigest()


def cache_isolation_key(
    *,
    match_id: str,
    video_sha256: str,
    events_sha256: str,
    strip_provenance: str,
) -> str:
    raw = f"{match_id}|{video_sha256}|{events_sha256}|{strip_provenance}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def assert_cache_binding(
    *,
    expected: Dict[str, str],
    cached: Dict[str, Any],
) -> Dict[str, Any]:
    """Reject mismatched/missing provenance — never silently fall back."""
    missing = [k for k in ("match_id", "video_sha256", "events_sha256", "strip_provenance") if k not in cached]
    if missing:
        return {
            "ok": False,
            "reason": "missing_provenance",
            "missing": missing,
            "action": "reject_cache",
            "render_ready": False,
        }
    mismatches = {
        k: {"expected": expected.get(k), "cached": cached.get(k)}
        for k in ("match_id", "video_sha256", "events_sha256", "strip_provenance")
        if str(expected.get(k)) != str(cached.get(k))
    }
    if mismatches:
        return {
            "ok": False,
            "reason": "provenance_mismatch",
            "mismatches": mismatches,
            "action": "reject_cache",
            "render_ready": False,
        }
    return {"ok": True, "action": "allow_cache", "render_ready": False}


def reject_forbidden_input_path(path: Path) -> Dict[str, Any]:
    name = Path(path).name
    if name in FORBIDDEN_INPUT_BASENAMES or any(name.endswith(s) for s in FORBIDDEN_NAME_SUFFIXES):
        return {
            "ok": False,
            "reason": "forbidden_filename",
            "path": str(path),
            "action": "reject_input",
            "render_ready": False,
        }
    return {"ok": True, "path": str(path), "render_ready": False}


def reject_forbidden_payload(obj: Dict[str, Any]) -> Dict[str, Any]:
    hits = [k for k in FORBIDDEN_TOP_KEYS if k in obj]
    if hits:
        return {
            "ok": False,
            "reason": "forbidden_top_level_keys",
            "hits": hits,
            "action": "reject_input",
            "render_ready": False,
        }
    return {"ok": True, "render_ready": False}


def t01_arc_roles_for_goal_count(n_goals: int) -> Dict[str, Any]:
    """Abstract T01 skeleton: narrative roles are NOT 1:1 with fixed five goals."""
    if n_goals <= 0:
        return {
            "schema": "v2_g0_t01_arc_v1",
            "status": "no_comeback_or_unresolved",
            "roles": [],
            "render_ready": False,
            "note": "Do not fabricate a comeback story",
        }
    # Minimal comeback needs at least deficit + equalizer + lead (often 3 goals on arc).
    if n_goals == 1:
        roles = ["opening_or_sole_goal"]
        status = "insufficient_for_full_t01"
    elif n_goals == 2:
        roles = ["deficit_or_equalizer", "lead_or_equalizer"]
        status = "partial_t01_candidate"
    elif n_goals == 3:
        roles = ["opening_deficit", "equalizer", "go_ahead"]
        status = "t01_minimal_arc"
    else:
        roles = ["opening_deficit", "equalizer", "go_ahead"] + [
            f"extend_or_context_{i}" for i in range(n_goals - 3)
        ]
        status = "t01_extended_arc"
    return {
        "schema": "v2_g0_t01_arc_v1",
        "n_goals": n_goals,
        "status": status,
        "roles": roles,
        "render_ready": False,
        "note": "Roles describe narrative function; do not require len(goals)==5",
    }


def classify_side_protagonist(
    *,
    score_path: Sequence[Tuple[int, int]],
    final_left_lead: Optional[bool] = None,
) -> Dict[str, Any]:
    """Synthetic helper: left vs right final lead; no_comeback if never trailed then led."""
    if len(score_path) < 2:
        return {"protagonist_side": "unknown", "comeback": False, "render_ready": False}
    # Simple board-order heuristic for synthetic tests only.
    saw_left_trail = any(a < b for a, b in score_path)
    saw_right_trail = any(a > b for a, b in score_path)
    end = score_path[-1]
    left_leads = end[0] > end[1]
    right_leads = end[1] > end[0]
    if left_leads and saw_left_trail:
        return {"protagonist_side": "left", "comeback": True, "render_ready": False}
    if right_leads and saw_right_trail:
        return {"protagonist_side": "right", "comeback": True, "render_ready": False}
    return {
        "protagonist_side": "left" if left_leads else ("right" if right_leads else "draw"),
        "comeback": False,
        "status": "no_comeback",
        "render_ready": False,
        "note": "Must not force T01 story when comeback=false",
    }


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_match_id(value: str) -> str:
    """Auditable normalization: NFKC-ish whitespace collapse + casefold; no fuzzy substring match."""
    text = str(value or "").strip()
    text = " ".join(text.replace("_", " ").replace("-", " ").split())
    return text.casefold()


def assert_match_id_consistent(*, cli_match_id: str, events_match_id: Optional[str]) -> Dict[str, Any]:
    if not cli_match_id:
        return {"ok": False, "reason": "missing_cli_match_id", "action": "reject_input", "render_ready": False}
    if not events_match_id:
        return {
            "ok": False,
            "reason": "missing_events_match_id",
            "action": "reject_input",
            "render_ready": False,
        }
    a = normalize_match_id(cli_match_id)
    b = normalize_match_id(str(events_match_id))
    if a != b:
        return {
            "ok": False,
            "reason": "match_id_mismatch",
            "cli_match_id": cli_match_id,
            "events_match_id": events_match_id,
            "normalized": {"cli": a, "events": b},
            "action": "reject_input",
            "render_ready": False,
        }
    return {"ok": True, "match_id": cli_match_id, "render_ready": False}


def build_strip_provenance(
    *,
    run_id: str,
    events_sha256: str,
    algo_root: str,
    algo_version: str,
    prediction_mode: str,
) -> Dict[str, str]:
    """Structured strip provenance — arbitrary algo_predicted:x strings are insufficient alone."""
    if prediction_mode in ("gold_clips", "gold_events", "gold"):
        raise ValueError(f"refusing gold strip provenance mode={prediction_mode}")
    if not run_id or not events_sha256 or not algo_root or not algo_version:
        raise ValueError("strip provenance requires run_id, events_sha256, algo_root, algo_version")
    token = (
        f"algo_predicted|run={run_id}|events={events_sha256[:16]}|"
        f"algo={algo_version}|mode={prediction_mode}|root={algo_root}"
    )
    return {
        "strip_provenance": token,
        "run_id": run_id,
        "events_sha256": events_sha256,
        "algo_root": algo_root,
        "algo_version": algo_version,
        "prediction_mode": prediction_mode,
    }


def validate_strip_bundle_provenance(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Reject gold-clip / gold-event dumps even if filename looks innocent."""
    mode = str(bundle.get("mode") or (bundle.get("config") or {}).get("mode") or "")
    event_source = str((bundle.get("config") or {}).get("event_source") or "")
    pipeline = str((bundle.get("config") or {}).get("pipeline") or "")
    if any(x in mode for x in ("gold_clips", "gold")) or event_source in ("gold_events", "gold"):
        return {
            "ok": False,
            "reason": "gold_strip_provenance",
            "mode": mode,
            "event_source": event_source,
            "action": "reject_strips",
            "render_ready": False,
        }
    if "gold" in pipeline.lower():
        return {
            "ok": False,
            "reason": "gold_strip_pipeline",
            "pipeline": pipeline,
            "action": "reject_strips",
            "render_ready": False,
        }
    # Per-chain gold payloads
    for c in bundle.get("chains") or []:
        if isinstance(c, dict) and "gold" in c and c.get("gold"):
            return {
                "ok": False,
                "reason": "chain_embeds_gold_field",
                "action": "reject_strips",
                "render_ready": False,
            }
    return {"ok": True, "mode": mode or bundle.get("prediction_source"), "render_ready": False}


def assert_verify_cache_entry(
    *,
    expected: Dict[str, str],
    cache_dir: Path,
    event_id: str,
) -> Dict[str, Any]:
    """Fail closed: missing provenance.json or content mismatch → reject (no silent fill)."""
    cache_dir = Path(cache_dir)
    prov_path = cache_dir / "provenance.json"
    payload_path = cache_dir / "original_goal_verify.json"
    if not payload_path.is_file():
        return {
            "ok": False,
            "reason": "missing_verify_payload",
            "event_id": event_id,
            "path": str(payload_path),
            "action": "reject_cache",
            "render_ready": False,
        }
    if not prov_path.is_file():
        return {
            "ok": False,
            "reason": "missing_provenance_fail_closed",
            "event_id": event_id,
            "path": str(prov_path),
            "note": "Legacy Croatia caches without provenance are rejected",
            "action": "reject_cache",
            "render_ready": False,
        }
    try:
        cached = json.loads(prov_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "reason": "provenance_unreadable",
            "error": str(exc),
            "action": "reject_cache",
            "render_ready": False,
        }
    if str(cached.get("event_id") or "") not in ("", str(event_id)) and str(cached.get("event_id")) != str(event_id):
        return {
            "ok": False,
            "reason": "event_id_mismatch",
            "expected_event_id": event_id,
            "cached_event_id": cached.get("event_id"),
            "action": "reject_cache",
            "render_ready": False,
        }
    bind = assert_cache_binding(expected=expected, cached=cached)
    if not bind.get("ok"):
        return bind
    # Optional content anchors
    for key in ("video_pts_anchor", "evidence_sha256"):
        if key in expected and key in cached and str(expected[key]) != str(cached[key]):
            return {
                "ok": False,
                "reason": f"{key}_mismatch",
                "action": "reject_cache",
                "render_ready": False,
            }
    return {"ok": True, "action": "allow_cache", "event_id": event_id, "render_ready": False}
