"""Recover complete, evidence-checkable judgments from truncated model JSON.

Distinguishes integrity statuses from model semantic UNRESOLVED:
  OUTPUT_TRUNCATED | PARSE_FAILED | EVIDENCE_UNCHECKABLE | UNRESOLVED | RECOVERED_PARTIAL_RESPONSE

Never invents missing fields or quality labels.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set


ALLOWED_QUALITY = frozenset({"BETTER", "SAME", "WORSE", "UNRESOLVED"})
REQUIRED_FIELDS = (
    "intent_id",
    "quality_judgment",
    "evidence_sufficiency",
    "confidence",
    "observed_visuals",
)


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def extract_complete_array_objects(
    text: str,
    *,
    array_key: str = "per_revision_judgments",
) -> Dict[str, Any]:
    """Decode only complete JSON objects inside a named array (stop at first incomplete)."""
    m = re.search(rf'"{re.escape(array_key)}"\s*:\s*\[', text or "")
    if not m:
        return {
            "objects": [],
            "array_found": False,
            "stop_reason": "array_not_found",
            "char_offset_stop": None,
        }
    i = m.end()
    dec = json.JSONDecoder()
    objects: List[Dict[str, Any]] = []
    while i < len(text):
        while i < len(text) and text[i] in " \n\r\t,":
            i += 1
        if i >= len(text):
            return {
                "objects": objects,
                "array_found": True,
                "stop_reason": "eof_without_array_close",
                "char_offset_stop": i,
            }
        if text[i] == "]":
            return {
                "objects": objects,
                "array_found": True,
                "stop_reason": "array_closed",
                "char_offset_stop": None,
            }
        try:
            obj, end = dec.raw_decode(text, i)
        except json.JSONDecodeError as exc:
            return {
                "objects": objects,
                "array_found": True,
                "stop_reason": f"object_decode_stopped:{exc}",
                "char_offset_stop": i,
            }
        if isinstance(obj, dict):
            objects.append({"object": obj, "char_start": i, "char_end": end})
        i = end
    return {
        "objects": objects,
        "array_found": True,
        "stop_reason": "eof",
        "char_offset_stop": len(text),
    }


def _map_time_tokens(text: str, sent: Set[str]) -> List[str]:
    tokens = set(re.findall(r"t\d+p\d+", text or ""))
    cited: List[str] = []
    for tok in tokens:
        hits = [s for s in sent if s.endswith("_" + tok) or s.endswith(tok)]
        if len(hits) == 1:
            cited.append(hits[0])
    return sorted(set(cited))


def check_evidence_bindings(
    judgment: Mapping[str, Any],
    *,
    sent_frame_ids: Sequence[str],
) -> Dict[str, Any]:
    sent = {str(x) for x in sent_frame_ids}
    cited: List[str] = []
    missing: List[str] = []
    method = "none"
    refs = judgment.get("evidence_refs")
    if isinstance(refs, list) and refs:
        method = "structured_evidence_refs"
        for ref in refs:
            if isinstance(ref, dict):
                fid = str(ref.get("frame_id") or ref.get("ref") or ref.get("id") or "")
            else:
                fid = str(ref)
            if not fid:
                continue
            if fid in sent:
                cited.append(fid)
            else:
                missing.append(fid)
    obs = str(judgment.get("observed_visuals") or "") + " " + str(judgment.get("reasons") or "")
    full = [s for s in sent if s in obs]
    if full:
        cited = sorted(set(cited) | set(full))
        if method == "none":
            method = "full_frame_id_in_observed_text"
    if method == "none":
        tok_cited = _map_time_tokens(obs, sent)
        if tok_cited:
            cited = sorted(set(cited) | set(tok_cited))
            method = "unique_time_token_in_observed_text"
    has_b = any(c.startswith("baseline_") for c in cited)
    has_c = any(c.startswith("candidate_") for c in cited)
    q = str(judgment.get("quality_judgment") or "").upper()
    if q == "UNRESOLVED":
        ok = True  # unresolved need not cite both sides
    else:
        ok = bool(cited) and has_b and has_c and not missing
    return {
        "ok": ok,
        "method": method,
        "cited_sent_frame_ids": sorted(set(cited)),
        "missing_frame_ids": sorted(set(missing)),
        "has_baseline_citation": has_b,
        "has_candidate_citation": has_c,
    }


def validate_recovered_judgment(
    wrap: Mapping[str, Any],
    *,
    sent_frame_ids: Sequence[str],
) -> Dict[str, Any]:
    j = wrap.get("object") if isinstance(wrap.get("object"), dict) else {}
    issues: List[str] = []
    for k in REQUIRED_FIELDS:
        if k not in j:
            issues.append(f"missing_field:{k}")
        elif j[k] is None or (isinstance(j[k], str) and not str(j[k]).strip()):
            issues.append(f"empty_field:{k}")
    q = str(j.get("quality_judgment") or "").upper()
    if q not in ALLOWED_QUALITY:
        issues.append(f"invalid_quality_judgment:{j.get('quality_judgment')}")
    try:
        conf = float(j.get("confidence"))
        if not 0.0 <= conf <= 1.0:
            issues.append("confidence_out_of_range")
    except (TypeError, ValueError):
        issues.append("confidence_not_numeric")
        conf = None
    ev = check_evidence_bindings(j, sent_frame_ids=sent_frame_ids)
    if q != "UNRESOLVED" and not ev["ok"]:
        issues.append("EVIDENCE_UNCHECKABLE")
    valid = not issues
    return {
        "valid": valid,
        "issues": issues,
        "intent_id": j.get("intent_id"),
        "quality_judgment": q if q in ALLOWED_QUALITY else None,
        "confidence": conf,
        "evidence_check": ev,
        "char_start": wrap.get("char_start"),
        "char_end": wrap.get("char_end"),
        "fields_present": sorted(j.keys()),
        "judgment": j if valid else None,
        "rejection_class": None
        if valid
        else (
            "EVIDENCE_UNCHECKABLE"
            if "EVIDENCE_UNCHECKABLE" in issues
            else "INVALID_FIELDS"
        ),
    }


def recover_per_revision_judgments(
    raw_text: str,
    *,
    sent_frame_ids: Sequence[str],
    finish_reason: Optional[str] = None,
    parse_error: Optional[str] = None,
) -> Dict[str, Any]:
    """Main entry: salvage complete checkable judgments from a (possibly truncated) response."""
    text = raw_text or ""
    raw_sha = sha256_text(text)
    status_tags: List[str] = []
    if str(finish_reason or "").lower() == "length":
        status_tags.append("OUTPUT_TRUNCATED")
    full_ok = False
    full_err = parse_error
    try:
        json.loads(text)
        full_ok = True
    except Exception as exc:  # noqa: BLE001
        full_err = full_err or f"{type(exc).__name__}:{exc}"
        status_tags.append("PARSE_FAILED")

    extracted = extract_complete_array_objects(text)
    recovered: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for wrap in extracted["objects"]:
        v = validate_recovered_judgment(wrap, sent_frame_ids=sent_frame_ids)
        if v["valid"]:
            q = v["quality_judgment"]
            recovered.append(
                {
                    "schema": "v3a_recovered_judgment_v1",
                    "recovery_status": "RECOVERED_PARTIAL_RESPONSE"
                    if ("OUTPUT_TRUNCATED" in status_tags or "PARSE_FAILED" in status_tags)
                    else "RECOVERED_FULL_RESPONSE",
                    "intent_id": v["intent_id"],
                    "quality_judgment": q,
                    "judgment": v["judgment"],
                    "evidence_check": v["evidence_check"],
                    "source": {
                        "raw_response_sha256": raw_sha,
                        "char_start": v["char_start"],
                        "char_end": v["char_end"],
                        "fields_from_model": v["fields_present"],
                        "no_fields_invented": True,
                    },
                    "status_distinction": {
                        "OUTPUT_TRUNCATED": "OUTPUT_TRUNCATED" in status_tags,
                        "PARSE_FAILED": "PARSE_FAILED" in status_tags,
                        "EVIDENCE_UNCHECKABLE": False,
                        "model_UNRESOLVED": q == "UNRESOLVED",
                        "note": (
                            "OUTPUT_TRUNCATED/PARSE_FAILED/EVIDENCE_UNCHECKABLE are integrity "
                            "statuses; model_UNRESOLVED is only quality_judgment==UNRESOLVED."
                        ),
                    },
                }
            )
        else:
            rejected.append(
                {
                    "recovery_status": f"RECOVERY_REJECTED_{v['rejection_class']}",
                    "intent_id": v.get("intent_id"),
                    "quality_judgment_raw": (wrap.get("object") or {}).get("quality_judgment"),
                    "issues": v["issues"],
                    "evidence_check": v["evidence_check"],
                    "char_start": v["char_start"],
                    "char_end": v["char_end"],
                    "status_distinction": {
                        "OUTPUT_TRUNCATED": "OUTPUT_TRUNCATED" in status_tags,
                        "PARSE_FAILED": "PARSE_FAILED" in status_tags,
                        "EVIDENCE_UNCHECKABLE": v["rejection_class"] == "EVIDENCE_UNCHECKABLE",
                        "model_UNRESOLVED": False,
                        "note": "Rejected recovery is not model UNRESOLVED.",
                    },
                }
            )

    return {
        "schema": "v3a_truncated_response_recovery_v1",
        "raw_response_sha256": raw_sha,
        "status_tags": status_tags,
        "finish_reason": finish_reason,
        "full_json_parse_ok": full_ok,
        "full_json_parse_error": full_err,
        "extraction": {
            "array_found": extracted["array_found"],
            "stop_reason": extracted["stop_reason"],
            "char_offset_stop": extracted["char_offset_stop"],
            "n_syntax_complete_objects": len(extracted["objects"]),
        },
        "n_valid_recovered": len(recovered),
        "n_rejected": len(rejected),
        "recovered": recovered,
        "rejected": rejected,
        "short_output_hint": (
            "Prefer per-revision compact JSON with mandatory evidence_refs "
            "[{frame_id,note}] to reduce truncation."
        ),
    }


# Compact schema reminder for paid verifier prompts (engineering hint only).
SHORT_PER_REVISION_JSON_SCHEMA = (
    '{"per_revision_judgments":[{'
    '"intent_id":str,"issue_id":str,'
    '"quality_judgment":"BETTER|SAME|WORSE|UNRESOLVED",'
    '"evidence_sufficiency":"HIGH|MEDIUM|LOW|INSUFFICIENT",'
    '"confidence":0-1,'
    '"original_issue_resolved":bool,'
    '"introduced_new_defect":bool,'
    '"observed_visuals":str,'
    '"evidence_refs":[{"frame_id":str,"note":str}]'
    "}]}"
)
