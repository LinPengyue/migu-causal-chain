"""Phase10: validated HUMAN benchmark labels for long-range football stories.

These labels are *not* inference-time inputs for V3-A. A narrative link is
different from a factual/causal assertion; annotations never manufacture PTS.
Standard library only; suitable for zero-HTTP offline data preparation.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, Mapping, Sequence

SCHEMA = "migu_long_range_story_chain_v1"
DATA_ROLE = "BENCHMARK_GOLD"
TEMPLATE_TYPES = frozenset({
    "comeback", "last_minute_winner", "redemption", "tactical_duel",
    "controversy_turning_point", "underdog_triumph", "open",
})
NODE_TYPES = frozenset({"match_state", "atomic_event", "short_causal_chain", "narrative_state"})
NARRATIVE_ROLES = frozenset({
    "context", "setup", "development", "turning_point", "climax", "resolution",
})
EDGE_TYPES = frozenset({"temporal", "causal", "enables", "contrasts", "resolves", "narrative_support"})
ASSERTION_STATUSES = frozenset({"confirmed", "inferred", "uncertain"})
EVIDENCE_SOURCES = frozenset({"source_video", "event_annotation", "short_chain_annotation", "scoreboard"})
SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonnegative_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0.0
    )


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(_text(item) for item in value)


def _has_cycle(edges: Sequence[tuple[str, str]]) -> bool:
    graph: Dict[str, list[str]] = {}
    for a, b in edges:
        graph.setdefault(a, []).append(b)
    seen: set[str] = set()
    active: set[str] = set()

    def visit(node: str) -> bool:
        if node in active:
            return True
        if node in seen:
            return False
        active.add(node)
        for nxt in graph.get(node, []):
            if visit(nxt):
                return True
        active.remove(node)
        seen.add(node)
        return False

    return any(visit(node) for node in graph if node not in seen)


def validate_long_story_chain(document: Mapping[str, Any]) -> Dict[str, Any]:
    """Fail-closed structural validation; DOES NOT certify narrative truth.

    Human annotation status and video evidence provenance remain externally
    adjudicated; this only checks consistency, links, and source bindings.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(document, Mapping):
        return {"valid": False, "errors": ["root must be an object"], "warnings": []}
    if document.get("schema") != SCHEMA:
        errors.append("schema must be " + SCHEMA)
    if document.get("data_role") != DATA_ROLE:
        errors.append("data_role must be BENCHMARK_GOLD; gold is forbidden in Agent inference inputs")
    for field in ("match_id", "story_id", "story_goal", "annotator_id"):
        if not _text(document.get(field)):
            errors.append(field + " must be a non-empty string")
    sha = document.get("source_video_sha256")
    if not isinstance(sha, str) or not SHA256.fullmatch(sha):
        errors.append("source_video_sha256 must be a 64-hex digest")
    if document.get("split") not in ("train", "dev", "test"):
        errors.append("split must be train/dev/test")
    if document.get("template_type") not in TEMPLATE_TYPES:
        errors.append("invalid template_type; use open if no preset fits")
    if document.get("annotation_status") not in ("draft", "adjudicated"):
        errors.append("annotation_status must be draft/adjudicated")

    nodes = document.get("nodes")
    edges = document.get("edges")
    if not isinstance(nodes, list) or len(nodes) < 2:
        errors.append("nodes must contain at least two long-range narrative units")
        nodes = nodes if isinstance(nodes, list) else []
    if not isinstance(edges, list) or not edges:
        errors.append("edges must contain at least one labeled relation")
        edges = edges if isinstance(edges, list) else []

    node_ids: set[str] = set()
    referenced_events = 0
    for i, node in enumerate(nodes):
        tag = f"nodes[{i}]"
        if not isinstance(node, Mapping):
            errors.append(tag + " must be an object")
            continue
        nid = node.get("node_id")
        if not _text(nid):
            errors.append(tag + ".node_id missing")
        elif nid in node_ids:
            errors.append(tag + ".node_id duplicate")
        else:
            node_ids.add(nid)
        if node.get("node_type") not in NODE_TYPES:
            errors.append(tag + ".node_type invalid")
        if node.get("narrative_role") not in NARRATIVE_ROLES:
            errors.append(tag + ".narrative_role invalid")
        if node.get("assertion_status") not in ASSERTION_STATUSES:
            errors.append(tag + ".assertion_status invalid")
        if not _text(node.get("description")):
            errors.append(tag + ".description missing")
        ids = node.get("event_ids", [])
        chain_ids = node.get("short_chain_ids", [])
        if not _strings(ids) or not _strings(chain_ids):
            errors.append(tag + ".event_ids/short_chain_ids must be string lists")
            ids, chain_ids = [], []
        referenced_events += len(ids) + len(chain_ids)
        windows = node.get("source_windows", [])
        if not isinstance(windows, list):
            errors.append(tag + ".source_windows must be a list")
            windows = []
        if not ids and not chain_ids and not windows:
            errors.append(tag + " requires event_ids, short_chain_ids or source_windows")
        for j, w in enumerate(windows):
            wtag = f"{tag}.source_windows[{j}]"
            if not isinstance(w, Mapping):
                errors.append(wtag + " must be an object")
                continue
            start, end = w.get("start_sec"), w.get("end_sec")
            if not (_nonnegative_number(start) and _nonnegative_number(end) and float(end) > float(start)):
                errors.append(wtag + " invalid source PTS interval")
            if w.get("live_status") not in ("FIRST_LIVE", "UNVERIFIED"):
                errors.append(wtag + " only FIRST_LIVE/UNVERIFIED allowed; replay forbidden")
            if w.get("live_status") == "UNVERIFIED":
                warnings.append(wtag + " lacks first-live confirmation")

    if referenced_events == 0:
        errors.append("story must link to existing events or short causal chains")

    edge_ids: set[str] = set()
    directed_edges: list[tuple[str, str]] = []
    for i, edge in enumerate(edges):
        tag = f"edges[{i}]"
        if not isinstance(edge, Mapping):
            errors.append(tag + " must be an object")
            continue
        eid, src, dst = edge.get("edge_id"), edge.get("from_node"), edge.get("to_node")
        if not _text(eid):
            errors.append(tag + ".edge_id missing")
        elif eid in edge_ids:
            errors.append(tag + ".edge_id duplicate")
        else:
            edge_ids.add(eid)
        if not _text(src) or src not in node_ids or not _text(dst) or dst not in node_ids:
            errors.append(tag + " dangling node reference")
        if src == dst:
            errors.append(tag + " self-edge forbidden")
        kind = edge.get("relation")
        if kind not in EDGE_TYPES:
            errors.append(tag + ".relation invalid")
        status = edge.get("assertion_status")
        if status not in ASSERTION_STATUSES:
            errors.append(tag + ".assertion_status invalid")
        if not _text(edge.get("rationale")):
            errors.append(tag + ".rationale missing")
        evidence = edge.get("evidence", [])
        if not isinstance(evidence, list):
            errors.append(tag + ".evidence must be a list")
            evidence = []
        for j, proof in enumerate(evidence):
            if not isinstance(proof, Mapping) or proof.get("source") not in EVIDENCE_SOURCES or not _text(proof.get("ref")):
                errors.append(f"{tag}.evidence[{j}] invalid evidence reference")
        if kind in ("causal", "enables") and status == "confirmed" and not evidence:
            errors.append(tag + " confirmed causal/enabling relation requires evidence")
        if kind in ("temporal", "causal", "enables") and src in node_ids and dst in node_ids and src != dst:
            directed_edges.append((src, dst))
    if _has_cycle(directed_edges):
        errors.append("temporal/causal/enabling dependency graph has a cycle")

    if document.get("annotation_status") == "adjudicated" and warnings:
        warnings.append("adjudicated label contains unverified first-live evidence; review before release")
    return {
        "schema": "migu_story_chain_validation_v1",
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "story_id": document.get("story_id"),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "benchmark_only": True,
        "semantic_truth_verified": False,
    }
