"""Versioned first-live evidence binding (append-only; never silent overwrite).

Used to ingest an audited paid visual verification pack into a *new* evidence
version while keeping prior manifests immutable. Does not auto-release.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .pipeline import dump

_PTS_TOL = 0.05


def _pts_eq(a: Any, b: Any, tol: float = _PTS_TOL) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(8 * 1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_paid_binding(
    *,
    paid_verify: Mapping[str, Any],
    expected_sha256: str,
    expected_segment_id: str,
    expected_event_id: str,
    expected_media_in: float,
    expected_media_out: float,
) -> Dict[str, Any]:
    """Fail-closed checks before any status write."""
    errors: List[str] = []
    sha = str(paid_verify.get("source_video_sha256") or "")
    if sha != expected_sha256:
        errors.append("source_video_sha256_mismatch")
    if str(paid_verify.get("segment_id") or "") != expected_segment_id:
        errors.append("segment_id_mismatch")
    pts = paid_verify.get("source_pts") or {}
    if not _pts_eq(pts.get("media_in"), expected_media_in) or not _pts_eq(
        pts.get("media_out"), expected_media_out
    ):
        errors.append("observation_window_mismatch")
    eid = str(paid_verify.get("event_id_from_b_manifest") or paid_verify.get("event_id") or "")
    if eid != expected_event_id:
        errors.append("event_id_mismatch")
    if str(paid_verify.get("final_first_live_status") or "") != "FIRST_LIVE_VERIFIED":
        errors.append("paid_status_not_verified")
    if str(paid_verify.get("agreement") or "") not in (
        "consistent",
        "agreed_verified_but_evidence_gate_failed",
    ):
        # only allow consistent dual-call agreement into versioned VERIFIED
        if str(paid_verify.get("agreement")) != "consistent":
            errors.append("paid_agreement_not_consistent")
    # Residual visual uncertainty from prior audit: score confirmation outside window.
    score_confirm = paid_verify.get("score_confirmation_sec")
    residual: List[str] = []
    try:
        if score_confirm is not None and float(score_confirm) > float(expected_media_out) + 1e-6:
            residual.append("score_confirmation_outside_observation_window")
    except (TypeError, ValueError):
        residual.append("score_confirmation_unparseable")
    return {
        "ok": not errors,
        "errors": errors,
        "residual_risks": residual,
        "requires_human_review": bool(residual) or bool(errors),
    }


def apply_versioned_equalizer_binding(
    *,
    prior_manifest_path: Path,
    paid_verify_path: Path,
    out_dir: Path,
    code_sha: str,
    audit_pack_path: Optional[Path] = None,
    force_human_review: bool = True,
) -> Dict[str, Any]:
    """Write a new evidence version; never mutate prior_manifest_path in place.

    Equalizer may become FIRST_LIVE_VERIFIED only when binding validates.
    If residual visual risks remain, status is recorded as POSSIBLE_FIRST_LIVE
    (or keeps UNRESOLVED) and human_review remains required — never RELEASE_READY.
    Other goals stay UNRESOLVED.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    prior = _load_json(prior_manifest_path)
    paid = _load_json(paid_verify_path)

    expected_sha = str(prior.get("source_video_sha256") or "")
    eq = None
    for g in prior.get("goals") or []:
        if str(g.get("segment_id")) == "seg_equalizer_goal_action":
            eq = g
            break
    if eq is None:
        raise ValueError("equalizer_goal_missing_in_prior_manifest")

    eids = [str(x) for x in (eq.get("event_ids") or [])]
    expected_eid = eids[0] if eids else ""
    binding = validate_paid_binding(
        paid_verify=paid,
        expected_sha256=expected_sha,
        expected_segment_id="seg_equalizer_goal_action",
        expected_event_id=expected_eid,
        expected_media_in=float(eq.get("media_in")),
        expected_media_out=float(eq.get("media_out")),
    )

    version_id = datetime.now(timezone.utc).strftime("v%Y%m%dT%H%M%SZ")
    version_dir = out / "versions" / version_id
    version_dir.mkdir(parents=True, exist_ok=True)

    # Immutable copy of prior
    dump(version_dir / "prior_manifest.immutable.json", prior)
    prior_sha = _sha256_file(Path(prior_manifest_path))
    (version_dir / "prior_manifest.sha256").write_text(prior_sha + "\n", encoding="utf-8")

    new_goals: List[Dict[str, Any]] = []
    for g in prior.get("goals") or []:
        row = dict(g)
        if str(row.get("segment_id")) != "seg_equalizer_goal_action":
            # Never silently upgrade other goals from this pack.
            row["first_live_status"] = str(row.get("first_live_status") or "UNRESOLVED")
            row["versioned_update"] = False
            new_goals.append(row)
            continue

        row = dict(row)
        row["versioned_update"] = True
        row["paid_verify_path"] = str(paid_verify_path)
        row["paid_agreement"] = paid.get("agreement")
        row["paid_judgments"] = paid.get("judgments")
        row["observation_window"] = {
            "media_in": eq.get("media_in"),
            "media_out": eq.get("media_out"),
        }
        row["source_video_sha256"] = expected_sha
        row["event_ids"] = list(eids)
        row["binding_validation"] = binding

        if not binding["ok"]:
            row["first_live_status"] = "UNRESOLVED"
            row["versioned_status_reason"] = "binding_validation_failed:" + ",".join(
                binding["errors"]
            )
        elif binding["residual_risks"] or force_human_review:
            # Honest: dual-call VERIFIED exists, but residual risks → do not claim
            # release-grade FIRST_LIVE_VERIFIED into the delivery gate alone.
            row["first_live_status"] = "POSSIBLE_FIRST_LIVE"
            row["paid_claimed_status"] = "FIRST_LIVE_VERIFIED"
            row["versioned_status_reason"] = (
                "paid_verified_with_residual_risks_or_human_review_required:"
                + ",".join(binding["residual_risks"] or ["force_human_review"])
            )
            row["human_review_required"] = True
        else:
            row["first_live_status"] = "FIRST_LIVE_VERIFIED"
            row["versioned_status_reason"] = "paid_dual_call_bound_and_validated"
            row["human_review_required"] = False
        new_goals.append(row)

    counts: Dict[str, int] = {}
    for g in new_goals:
        st = str(g.get("first_live_status") or "UNRESOLVED")
        counts[st] = counts.get(st, 0) + 1

    manifest = {
        "schema": "v3a_versioned_final_goal_evidence_manifest_v1",
        "version_id": version_id,
        "parent_manifest_path": str(prior_manifest_path),
        "parent_manifest_sha256": prior_sha,
        "code_sha": code_sha,
        "source_video": prior.get("source_video"),
        "source_video_sha256": expected_sha,
        "n_goal_anchors": len(new_goals),
        "status_counts": counts,
        "any_first_live_verified": counts.get("FIRST_LIVE_VERIFIED", 0) > 0,
        "all_resolved_verified": (
            len(new_goals) > 0 and counts.get("FIRST_LIVE_VERIFIED", 0) == len(new_goals)
        ),
        "release_authorized": False,
        "delivery_label": "HUMAN_REVIEW_REQUIRED",
        "silent_overwrite": False,
        "goals": new_goals,
        "paid_verify_ingest": {
            "path": str(paid_verify_path),
            "binding": binding,
            "audit_pack_path": str(audit_pack_path) if audit_pack_path else None,
        },
        "note": (
            "Append-only versioned evidence. Prior manifest copied immutably. "
            "Other goals remain UNRESOLVED. Never auto-release from this ingest."
        ),
    }
    dump(version_dir / "final_goal_evidence_manifest.json", manifest)
    dump(out / "latest_version_pointer.json", {
        "version_id": version_id,
        "manifest_path": str(version_dir / "final_goal_evidence_manifest.json"),
        "release_authorized": False,
        "delivery_label": "HUMAN_REVIEW_REQUIRED",
    })
    # Convenience copy at out root without touching the historical B e2e tree.
    dump(out / "final_goal_evidence_manifest.versioned.json", manifest)
    return {
        "ok": True,
        "version_id": version_id,
        "version_dir": str(version_dir),
        "manifest": manifest,
        "binding": binding,
    }
