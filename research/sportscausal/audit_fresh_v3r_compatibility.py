"""Targeted compatibility regression on frozen A/B evidence; no media/HTTP/upstream rerun.

Rebuild ONLY R1 + fresh R2a.4 + R2bc + R3 in memory and compare exact
keeper/comeback candidates, material and legacy seed bytes against the old
cached-graph outputs. Optional original enriched event inputs check the
new score extractor on the same historical event stream.
"""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
from copy import deepcopy

from template_graph import read, write, check
from episode_semantics import normalize_for_episodes
from episode_patterns import match_episodes
from r2a4_relation_graph import build_role_graph
from r2a4_patterns import project_roles, match_mixed_alternation
import r2bc_patterns
import r3_story_pipeline as r3
from run_fresh_v3r_general import ROOT, sha256, load_upstream, make_score_doc

ART = ROOT / "artifacts"
CASES = {"A": "A_uae_oman", "B": "B_osasuna_celta"}


def compare(name, actual, expected, rows):
    if actual == expected:
        rows.append({"check": name, "pass": True})
        return
    rows.append({"check": name, "pass": False,
                 "actual_sha256": fingerprint(actual), "expected_sha256": fingerprint(expected),
                 "actual_type": type(actual).__name__, "expected_type": type(expected).__name__})


def fingerprint(obj):
    import json
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def score_signature(doc):
    return [{k: n.get(k) for k in ("score", "t_sec", "opening", "delta_side", "carrier_event_id")}
            for n in doc["score_path"]]


def regression(case, out, original_events=None):
    evidence_path = ART / "stage1_2_evidence_preflight_20261125" / CASES[case] / "keeper_rescue" / "evidence.json"
    sem_path = ART / "v3r_general_r2a2_preflight" / case / "normalized_semantics.json"
    score_path = ART / "v3r_general_r2a3_preflight" / "inputs_prepared" / (case + "_score_path_from_t01.json")
    a4dir = ART / "v3r_general_r2a4_preflight" / case
    bcdir = ART / "v3r_general_r2bc_preflight" / case
    r3dir = ART / "v3r_general_r3_preflight" / case
    e, frozen_sem, score = read(evidence_path), read(sem_path), read(score_path)
    rows = []
    sem = normalize_for_episodes(e)
    compare("fresh_normalization", sem, frozen_sem, rows)
    fresh_graph = build_role_graph(sem, e, score)
    check(fresh_graph["reused_without_score_graph"] is False, "fresh graph must not use historical cache")
    old_graph = read(a4dir / "relation_graph.json")
    # Only cache provenance flag is permitted to differ here.
    for key in ("atoms", "edges", "rejected_edges", "unresolved_relations",
                "inferred_roles", "goal_bindings", "outcome_context_edges",
                "observation_tasks"):
        compare("role_graph:" + key, fresh_graph[key], old_graph[key], rows)
    bundle = project_roles(fresh_graph)
    compare("episode_bundle", bundle, read(a4dir / "causal_episodes.json"), rows)
    kt, at = [read(ROOT / "patterns" / (tid + ".json")) for tid in ("keeper_rescue", "alternating_threats")]
    ra = {"keeper_rescue": match_episodes(kt, bundle),
          "alternating_threats": match_episodes(at, bundle),
          "alternating_threats_score_context": match_mixed_alternation(at, bundle)}
    for tid, res in ra.items():
        compare("r2a:" + tid, res["candidates"], read(a4dir / (tid + ".json"))["candidates"], rows)
    bc = r2bc_patterns.run(e, fresh_graph, bundle, score, r2bc_patterns.default_templates())
    for tid, res in bc["results"].items():
        compare("r2bc:" + tid, res["candidates"], read(bcdir / (tid + ".json"))["candidates"], rows)

    old_summary = read(r3dir / "summary.json")
    seeds = []
    for s in old_summary["stories"]:
        if s["legacy_seed"]["status"] == "preserved_legacy_seed":
            seed_path = (r3dir / s["folder"] / "legacy_seed.json").resolve()
            seeds.append({"story_id": s["story_id"], "video_id": e["video_id"],
                          "subjects": s["subjects"], "path": str(seed_path), "edl_key": "edl",
                          "sha256": s["legacy_seed"]["sha256"],
                          "source_provenance": s["legacy_seed"]["source_provenance"]})
    manifest = out / "legacy_manifest.json"
    write(manifest, {"schema": "sportscausal_legacy_seed_manifest_v1", "seeds": seeds})
    legacy = r3.load_seed_manifest(manifest)
    pack = r3.compile_pack(e, ra, bc, legacy=legacy)
    r3.write_pack(out / "r3", pack, legacy)
    compare("template_counts", pack["template_counts"], old_summary["template_counts"], rows)
    for s in old_summary["stories"]:
        sid = s["story_id"]
        if s["template_id"] not in {"keeper_rescue", "comeback"}:
            continue
        if sid not in pack["stories"]:
            rows.append({"check": sid + ":present", "pass": False})
            continue
        folder = s["folder"]
        for name in ("initial_edl.json", "story_graph.json", "materials.json",
                     "context_pool.json", "observation_tasks.json", "legacy_seed_metadata.json"):
            compare(sid + ":" + name, read(out / "r3" / folder / name),
                    read(r3dir / folder / name), rows)
        if sid in legacy:
            compare(sid + ":legacy_seed_bytes", sha256(out / "r3" / folder / "legacy_seed.json"),
                    s["legacy_seed"]["sha256"], rows)
    # No legacy replacement should be silently chosen by the new entry.
    for sid, b in pack["stories"].items():
        if b["story_graph"]["template_id"] == "keeper_rescue":
            compare(sid + ":agent_seed_file", b["story_graph"]["agent_seed"]["file"], "initial_edl.json", rows)
        elif sid in legacy:
            compare(sid + ":agent_seed_file", b["story_graph"]["agent_seed"]["file"], "legacy_seed.json", rows)

    score_status = "NOT_CHECKED_NO_ORIGINAL_ENRICHED_EVENTS"
    if original_events:
        # Optional source-bound original enriched native stream. Check exact
        # evidence event membership before using it to regenerate a path.
        native = read(original_events)
        from r3_legacy_agent_adapter import validate_source_events
        validate_source_events(e, native)
        _, _, scores = load_upstream()
        new_score = make_score_doc(native, e["video_id"], score["score_side_mapping"],
                                   "frozen historical mapping", scores.build_score_path)
        compare("regenerated_score_signature", score_signature(new_score), score_signature(score), rows)
        # Additional sparse-observation metadata is reported separately,
        # not silently discarded if it can affect downstream behavior.
        write(out / "regenerated_score_path.json", new_score)
        score_status = "CHECKED"
        compare("regenerated_full_score_rows", new_score["score_path"], score["score_path"], rows)
    report = {"case": case, "status": "PASS" if all(x["pass"] for x in rows) else "DIFFERENCES",
              "scope": "frozen evidence to R3; upstream prediction not repeated",
              "score_status": score_status, "checks": rows, "http_calls": 0}
    write(out / "regression.json", report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--a-events", type=Path, help="historical A events_enriched.json, optional")
    p.add_argument("--b-events", type=Path, help="historical B events_enriched.json, optional")
    a = p.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=False)
    reports = {}
    for case, events in (("A", a.a_events), ("B", a.b_events)):
        d = out / case
        d.mkdir()
        try:
            reports[case] = regression(case, d, events)
        except Exception as exc:
            reports[case] = {"case": case, "status": "ERROR", "error": type(exc).__name__ + ": " + str(exc)}
            write(d / "regression.json", reports[case])
    write(out / "summary.json", reports)
    if any(r["status"] != "PASS" for r in reports.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
