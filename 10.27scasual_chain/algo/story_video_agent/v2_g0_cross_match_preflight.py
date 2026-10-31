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
