"""VLM goal-action evidence semantics (fail-closed, match-agnostic).

Field meanings (do not collapse these):
  - goalmouth_or_net_visible: goal / net structure visible in frame.
    Legacy alias: observed_net. NEVER treat as goal-result confirmation.
  - observed_shot: a shot attempt is visible.
  - ball_crosses_goal_line: ball clearly crosses the goal line (stronger).
  - goal_result_confirmed: goal outcome confirmed in the observation (strongest).
  - supports_bound_segment: model explicitly endorses binding this window as
    the goal-action cut candidate (still NOT FIRST_LIVE_VERIFIED).

Scoreboard text such as 0-0 alone neither proves a goal occurred nor that it
did not occur (sparse frames often miss the score change).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

EVIDENCE_SUPPORTS_CANDIDATE_BIND = "SUPPORTS_CANDIDATE_BIND"
EVIDENCE_AMBIGUOUS = "AMBIGUOUS_EVIDENCE"
EVIDENCE_LACKS_SUPPORT = "LACKS_SUPPORT"

_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|authorization|passwd|password|secret|bearer|token)$",
    re.IGNORECASE,
)
_DATA_URI_IMAGE_RE = re.compile(
    r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+",
    re.IGNORECASE,
)
_ZERO_ZERO_RE = re.compile(r"0\s*[-–—:to]\s*0", re.IGNORECASE)


def text_mentions_scoreboard_zero_zero(text: Any) -> bool:
    """Heuristic only — never a proof of goal presence/absence."""
    s = str(text or "")
    if not s:
        return False
    return bool(_ZERO_ZERO_RE.search(s) or "0-0" in s.replace(" ", ""))


def _as_bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    return None


def normalize_goal_visibility_fields(vlm: Mapping[str, Any]) -> Dict[str, Any]:
    """Map legacy + new fields without inventing True."""
    vlm = vlm if isinstance(vlm, Mapping) else {}
    net_legacy = _as_bool(vlm.get("observed_net"))
    net_new = _as_bool(vlm.get("goalmouth_or_net_visible"))
    # Prefer explicit new field when present; else legacy observed_net.
    goalmouth = net_new if net_new is not None else net_legacy
    return {
        "observed_shot": _as_bool(vlm.get("observed_shot")),
        "goalmouth_or_net_visible": goalmouth,
        "observed_net_legacy": net_legacy,
        "ball_crosses_goal_line": _as_bool(vlm.get("ball_crosses_goal_line")),
        "goal_result_confirmed": _as_bool(vlm.get("goal_result_confirmed")),
        "supports_bound_segment": _as_bool(vlm.get("supports_bound_segment")),
        "scoreboard_only": vlm.get("scoreboard_only") is True,
        "live_or_replay": str(vlm.get("live_or_replay") or "").strip().lower(),
        "scoreboard_zero_zero_mentioned": text_mentions_scoreboard_zero_zero(
            f"{vlm.get('visible_content') or ''} {vlm.get('story_relation') or ''}"
        ),
        "notes": [
            "observed_net/goalmouth_or_net_visible != goal_result_confirmed",
            "scoreboard 0-0 alone neither proves nor disproves a goal",
        ],
    }


def classify_goal_action_evidence(vlm: Mapping[str, Any]) -> Dict[str, Any]:
    """Classify whether VLM fields may authorize a goal-action candidate bind/trim.

    Explicit supports_bound_segment=false is never overridden by shot&&net.
    Conflict / unclear semantics → AMBIGUOUS_EVIDENCE (not bindable).
    """
    fields = normalize_goal_visibility_fields(vlm)
    reasons: list[str] = []
    shot = fields["observed_shot"]
    goalmouth = fields["goalmouth_or_net_visible"]
    crosses = fields["ball_crosses_goal_line"]
    confirmed = fields["goal_result_confirmed"]
    supports = fields["supports_bound_segment"]

    if fields["scoreboard_only"]:
        return {
            "status": EVIDENCE_LACKS_SUPPORT,
            "reasons": ["scoreboard_only_not_goal_action"],
            "fields": fields,
            "bindable": False,
        }
    if fields["live_or_replay"] == "replay":
        return {
            "status": EVIDENCE_LACKS_SUPPORT,
            "reasons": ["replay_cannot_bind_primary_goal"],
            "fields": fields,
            "bindable": False,
        }

    # Explicit refusal — never let shot&&net or a candidate span override this.
    if supports is False:
        reasons.append("explicit_supports_bound_segment_false")
        if shot is True and goalmouth is True:
            reasons.append("shot_and_net_conflict_with_supports_false")
        if crosses is True or confirmed is True:
            reasons.append("stronger_goal_fields_conflict_with_supports_false")
        if fields["scoreboard_zero_zero_mentioned"]:
            reasons.append(
                "scoreboard_zero_zero_mentioned_not_decisive_but_supports_false"
            )
        return {
            "status": EVIDENCE_AMBIGUOUS,
            "reasons": reasons,
            "fields": fields,
            "bindable": False,
        }

    strong = confirmed is True or crosses is True
    if supports is True:
        if strong:
            return {
                "status": EVIDENCE_SUPPORTS_CANDIDATE_BIND,
                "reasons": ["explicit_supports_with_strong_goal_field"],
                "fields": fields,
                "bindable": True,
            }
        if shot is True:
            return {
                "status": EVIDENCE_SUPPORTS_CANDIDATE_BIND,
                "reasons": [
                    "explicit_supports_with_observed_shot",
                    "observed_net_not_treated_as_goal_confirmation",
                ],
                "fields": fields,
                "bindable": True,
            }
        if goalmouth is True and shot is not True:
            reasons.append("supports_true_but_only_goalmouth_without_shot")
            reasons.append("observed_net_is_not_goal_confirmation")
            return {
                "status": EVIDENCE_AMBIGUOUS,
                "reasons": reasons,
                "fields": fields,
                "bindable": False,
            }
        reasons.append("supports_true_without_action_fields")
        return {
            "status": EVIDENCE_AMBIGUOUS,
            "reasons": reasons,
            "fields": fields,
            "bindable": False,
        }

    # supports missing / null — do NOT promote via legacy shot&&net.
    if strong:
        return {
            "status": EVIDENCE_SUPPORTS_CANDIDATE_BIND,
            "reasons": ["strong_goal_field_without_supports_flag"],
            "fields": fields,
            "bindable": True,
        }
    if shot is True and goalmouth is True:
        reasons.append("shot_and_net_without_explicit_supports_bound_segment")
        reasons.append("observed_net_is_not_goal_confirmation")
        return {
            "status": EVIDENCE_AMBIGUOUS,
            "reasons": reasons,
            "fields": fields,
            "bindable": False,
        }
    if shot is True:
        reasons.append("shot_without_supports_or_goal_confirmation")
        return {
            "status": EVIDENCE_LACKS_SUPPORT,
            "reasons": reasons,
            "fields": fields,
            "bindable": False,
        }
    reasons.append("vlm_lacks_goal_action_support_fields")
    if fields["scoreboard_zero_zero_mentioned"]:
        reasons.append("scoreboard_zero_zero_alone_not_proof")
    return {
        "status": EVIDENCE_LACKS_SUPPORT,
        "reasons": reasons,
        "fields": fields,
        "bindable": False,
    }


def redact_audit_value(value: Any) -> Any:
    """Strip secrets and bulky image base64 from audit payloads."""
    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            ks = str(k)
            if _SECRET_KEY_RE.search(ks):
                out[ks] = "[REDACTED]"
            else:
                out[ks] = redact_audit_value(v)
        return out
    if isinstance(value, list):
        return [redact_audit_value(v) for v in value]
    if isinstance(value, str):
        if value.lower().startswith(("sk-", "bearer ")):
            return "[REDACTED]"
        if len(value) > 256 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", value or ""):
            # Likely raw base64 blob
            return f"[REDACTED_BASE64 len={len(value)}]"
        return _DATA_URI_IMAGE_RE.sub(
            lambda m: f"[REDACTED_DATA_URI_IMAGE len={len(m.group(0))}]",
            value,
        )
    return value


def persist_visible_model_output(
    audit_dir: Optional[Path],
    *,
    role: str,
    request_id: str,
    content: str,
    meta: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist full visible model text locally for audit (no paid API).

    Does not store API keys, Authorization headers, or image base64 payloads.
    """
    text = str(content or "")
    info: Dict[str, Any] = {
        "persisted": False,
        "visible_output_chars": len(text),
        "visible_output_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    if audit_dir is None:
        return info
    dest_dir = Path(audit_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_role = re.sub(r"[^\w.\-]+", "_", str(role or "role"))[:64]
    safe_id = re.sub(r"[^\w.\-]+", "_", str(request_id or "anon"))[:120] or "anon"
    path = dest_dir / f"{safe_role}_{safe_id}.json"
    payload = {
        "schema": "v3a_model_visible_output_v1",
        "role": role,
        "request_id": request_id,
        "visible_output_chars": info["visible_output_chars"],
        "visible_output_sha256": info["visible_output_sha256"],
        "content": text,
        "meta": redact_audit_value(dict(meta or {})),
        "redaction_note": (
            "Secrets (api_key/authorization/…) and data:image base64 are redacted "
            "from meta; content is model-visible text only."
        ),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    info["persisted"] = True
    info["visible_output_path"] = str(path)
    return info
