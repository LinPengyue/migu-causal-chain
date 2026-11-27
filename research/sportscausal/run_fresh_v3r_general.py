"""Fresh V3-R-General from native delivery inputs, without the old T01 editor.

Reuse 11.20 enrich, production rule-only strip, V1 adapter + Goal Recovery,
and stable score extractor. Keep R1/R2a.4/R2bc/R3 algorithms unchanged.
No paid API, no historical artifacts, no old Phase5 or Story Agent execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from template_graph import check, read, write, number, event_window
from evidence_representation import build_evidence
from episode_semantics import normalize_for_episodes
import r2a4_patterns
import r2bc_patterns
import r3_story_pipeline

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
DELIVERY = REPO / "11.20sstory_chain"
DELIVERY_REF = "93804fbf9591b54d86fb170385491ed4ced024bd"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", str(REPO), *args], text=True).strip()


def probe_video(path):
    info = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_format", "-show_streams",
        "-of", "json", str(path)
    ], text=True))
    duration = float(info["format"]["duration"])
    check(number(duration) and duration > 0 and any(
        s.get("codec_type") == "video" for s in info["streams"]), "invalid source video")
    return duration, info


def validate_native(doc):
    check(isinstance(doc, dict) and isinstance(doc.get("events"), list)
          and bool(doc["events"]), "nonempty native events list required")
    check(not doc.get("is_benchmark_gold") and "causal_chains" not in doc
          and "story_chains" not in doc, "native events must not contain reference chains")
    ids = [e.get("event_id") for e in doc["events"]]
    check(all(isinstance(x, str) and x.strip() for x in ids)
          and len(set(ids)) == len(ids), "event IDs missing/duplicate")
    teams = doc.get("teams")
    check(isinstance(teams, dict) and all(isinstance(teams.get(k), dict)
          and teams[k].get("name") for k in ("team_1", "team_2")), "native team metadata required")
    return doc


def score_mapping(doc, left_team=None, provenance=None):
    native = doc.get("score_side_mapping")
    if native is not None:
        check(isinstance(native, dict) and set(native) == {"left", "right"}
              and set(native.values()) == {"team_1", "team_2"}, "invalid native score mapping")
    if left_team is not None:
        check(left_team in {"team_1", "team_2"} and isinstance(provenance, str)
              and provenance.strip(), "explicit score mapping requires verification provenance")
        explicit = {"left": left_team, "right": "team_2" if left_team == "team_1" else "team_1"}
        check(native is None or native == explicit, "native/explicit score mapping conflict")
        return explicit, provenance
    check(native is not None, "score-side mapping absent: supply verified --score-left-team and --score-mapping-provenance")
    return native, "native score_side_mapping field"


def load_upstream():
    # The delivery root (not its algo subfolder) is required by run_strip_predict.
    # Protect the frozen delivery source and reject an accidentally modified worktree.
    check(subprocess.run(["git", "-C", str(REPO), "diff", "--quiet", DELIVERY_REF,
                          "--", "11.20sstory_chain"]).returncode == 0,
          "delivery differs from frozen 11.20 or baseline unavailable")
    for p in (DELIVERY / "algo", DELIVERY / "eval"):
        check(p.is_dir(), "delivery import directory missing: " + str(p))
        sys.path.insert(0, str(p))
    from story_video_agent_v3 import closed_loop_cli as closed
    from story_video_agent_v3 import atomic_event_enrich as enrich
    from story_video_agent import v2_strip_reinfer as strip_module
    from story_chain import score_path as scores
    import strip_adapter
    for module in (closed, enrich, strip_module, scores, strip_adapter):
        check(Path(module.__file__).resolve().is_relative_to(DELIVERY.resolve()),
              "non-delivery module imported: " + module.__name__)
    return closed, enrich, scores


def make_score_doc(events_doc, video_id, mapping, provenance, build_score_path):
    rows = [node.to_dict() for node in build_score_path(events_doc["events"])]
    # Empty path is genuine missing scoreboard evidence, not an invented 0:0.
    return {"video_id": video_id, "score_side_mapping": mapping,
            "score_mapping_provenance": provenance, "score_path": rows,
            "source": "11.20 story_chain.score_path.build_score_path on enriched native events",
            "teams_from_evidence": events_doc["teams"]}


def run(args):
    events_path = Path(args.match_json).resolve(strict=True)
    video = Path(args.source_mp4).resolve(strict=True)
    causal = Path(args.causal_atoms_json).resolve(strict=True) if args.causal_atoms_json else None
    independent = Path(args.independent_atoms_json).resolve(strict=True) if args.independent_atoms_json else None
    check(not (causal and independent), "choose one atom supplement source")
    check(not causal or args.allow_dev, "causal-derived atoms require --allow-dev")
    raw = validate_native(read(events_path))
    mapping, mapping_source = score_mapping(raw, args.score_left_team, args.score_mapping_provenance)
    # No arbitrary input from a reference story, or implicit sibling-file discovery.
    check(not causal or causal != events_path, "atom source must be separate from native events")
    check(not independent or independent != events_path, "atom source must be separate from native events")
    video_id = args.video_id or video.stem
    check(isinstance(video_id, str) and video_id.strip(), "empty video ID")
    selected = set(args.template_id or [])
    defaults = r2bc_patterns.default_templates()
    supported = {"keeper_rescue", "alternating_threats"} | {t["template_id"] for t in defaults}
    check(selected <= supported, "unknown/unimplemented template: " + str(sorted(selected - supported)))
    closed, enrich, scores = load_upstream()
    duration, media = probe_video(video)
    source_sha = sha256(video)
    raw_sha = sha256(events_path)
    atom_path = causal or independent
    atom_sha = sha256(atom_path) if atom_path else None
    check(not args.expected_events_sha256 or raw_sha == args.expected_events_sha256.lower(),
          "native event input hash mismatch")
    check(not args.expected_atom_source_sha256 or atom_sha == args.expected_atom_source_sha256.lower(),
          "atom supplement input hash mismatch")
    # Preserve invalid-window diagnostics in Evidence, but reject an entirely
    # incompatible source timeline before doing strip inference.
    n_valid_raw_windows = sum(event_window(e, duration) is not None for e in raw["events"])
    check(n_valid_raw_windows > 0, "no native event windows on supplied video timeline")
    check(not args.expected_source_sha256 or source_sha == args.expected_source_sha256.lower(),
          "source video hash mismatch")
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    audit = {
        "schema": "sportscausal_fresh_v3r_general_v1", "status": "RUNNING",
        "git_head": git("rev-parse", "HEAD"), "delivery_ref": DELIVERY_REF,
        "video_id": video_id, "duration_sec": duration,
        "inputs": {k: {"path": str(p), "sha256": h} for k,p,h in [
            ("match_json", events_path, raw_sha), ("source_mp4", video, source_sha),
            ("causal_atoms_json", causal, atom_sha if causal else None),
            ("independent_atoms_json", independent, atom_sha if independent else None)] if p},
        "score_side_mapping": mapping, "score_mapping_provenance": mapping_source,
        "n_raw_valid_media_windows": n_valid_raw_windows,
        "n_raw_events": len(raw["events"]),
        "identity_note": "Input paths and hashes record caller-selected pairing; not visual identity proof.",
        "entry_sha256": sha256(Path(__file__).resolve()),
        "requested_templates": sorted(selected) if selected else sorted(supported),
        "stages": [], "paid_api_enabled": False, "http_calls": 0,
        "quality_verified": False, "first_live_verified": False, "release_authorized": False,
        "argv": sys.argv,
    }
    write(out / "run_manifest.json", audit)
    write(out / "ffprobe.json", media)

    def completed(stage, **fields):
        audit["stages"].append({"stage": stage, **fields})
        write(out / "run_manifest.json", audit)

    try:
        d1, d2, d3 = [out / x for x in ("01_enrich", "02_strip831", "03_v1_adapt")]
        for d in (d1, d2, d3):
            d.mkdir()
        enriched_path = d1 / "events_enriched.json"
        report = enrich.enrich_files(events_path=events_path, causal_path=causal,
                    independent_atoms_path=independent, out_events_path=enriched_path,
                    out_report_path=d1 / "enrich_report.json")
        enriched = validate_native(read(enriched_path))
        expected_mode = ("HUMAN_ATOM_ENRICHED_DEV" if causal else
                         "INDEPENDENT_ATOMIC_ANNOTATED" if independent else "RAW_EVENTS_ONLY")
        check(report["input_mode"] == expected_mode, "unexpected enrichment provenance")
        check(enriched["teams"] == raw["teams"], "enrichment changed teams")
        original_by_id = {e["event_id"]: e for e in raw["events"]}
        merged_by_id = {e["event_id"]: e for e in enriched["events"]}
        check(all(merged_by_id.get(eid) == e for eid, e in original_by_id.items()),
              "enrichment lost or altered native events")
        audit["input_tier"] = expected_mode
        completed("01_enrich", n_raw=len(raw["events"]), n_enriched=len(enriched["events"]),
                  n_injected=report.get("n_injected"), sha256=sha256(enriched_path))
        strip = closed._run_strip(enriched_path, match_id=video_id, algo_root=DELIVERY, out_dir=d2)
        check(strip.get("use_llm") is False and strip.get("profile") == "production",
              "strip must use frozen production rule-only profile")
        completed("02_strip831", n_events=strip["n_events"], n_chains=strip["n_chains"],
                  sha256=sha256(d2 / "strip_A_original.json"))
        predicted_path = d3 / "predicted_causal.json"
        predicted = closed._adapt_v1(strip=strip, enriched_events=enriched_path, match_id=video_id,
                    video_name=video.name, out_path=predicted_path, strip_path=d2 / "strip_A_original.json",
                    recovery_out_path=d3 / "goal_recovery.json")
        check(predicted.get("v3_adapter", {}).get("human_causal_structure_used") is False,
              "unexpected human chain structure")
        completed("03_v1_adapt", n_chains=len(predicted["causal_chains"]), sha256=sha256(predicted_path))

        # Preserve full adapted chains: Evidence applies its original replay/member policy.
        # Do NOT use the old Phase5-only replay-goal filtering or execute T01 story planning.
        evidence = build_evidence(enriched, predicted, report, video_id=video_id,
                                  duration_sec=duration, allow_dev=args.allow_dev)
        evdir = out / "04_evidence"
        evdir.mkdir()
        write(evdir / "evidence.json", evidence)
        score_doc = make_score_doc(enriched, video_id, mapping, mapping_source, scores.build_score_path)
        write(evdir / "score_path.json", score_doc)
        completed("04_evidence", n_atoms=len(evidence["atoms"]), n_chains=len(evidence["chains"]),
                  n_score_nodes=len(score_doc["score_path"]), sha256=sha256(evdir / "evidence.json"))
        semantics = normalize_for_episodes(evidence)
        sdir = out / "05_r1"
        sdir.mkdir()
        write(sdir / "normalized_semantics.json", semantics)
        completed("05_r1", n_atoms=len(semantics["atoms"]))

        a4dir = out / "06_r2a4"
        atemplates = [read(ROOT / "patterns" / (tid + ".json"))
                      for tid in ("keeper_rescue", "alternating_threats")]
        # Fresh safe graph, not the historic R2a.3 ablation or score-inferred cache.
        r2a4_patterns.run(evidence, semantics, score_doc, atemplates, a4dir)
        completed("06_r2a4")
        bcdir = out / "07_r2bc"
        bcdir.mkdir()
        bc = r2bc_patterns.run(evidence, read(a4dir / "relation_graph.json"),
                read(a4dir / "causal_episodes.json"), score_doc, defaults)
        write(bcdir / "anchor_pack.json", bc)
        for tid, result in bc["results"].items():
            write(bcdir / (tid + ".json"), result)
        write(bcdir / "observation_tasks.json", {"video_id": video_id, "tasks": bc["observation_tasks"], "http_calls": 0})
        completed("07_r2bc", candidate_counts={k: len(v["candidates"]) for k,v in bc["results"].items()})
        aresults = {tid: read(a4dir / (tid + ".json")) for tid in r3_story_pipeline.R2A_RESULTS}
        # Compile the unchanged complete pack, then restrict materialized outputs
        # only if requested. Keep mixed score-context strictly separate from the 8 types.
        pack = r3_story_pipeline.compile_pack(evidence, aresults, bc)
        if selected:
            pack["stories"] = {sid: b for sid,b in pack["stories"].items()
                               if b["story_graph"]["template_id"] in selected}
            pack["template_counts"] = {k:v for k,v in pack["template_counts"].items() if k in selected}
        r3dir = out / "08_r3"
        r3_story_pipeline.write_pack(r3dir, pack, {})
        completed("08_r3", n_stories=len(pack["stories"]), template_counts=pack["template_counts"])
        audit["status"] = "COMPLETE"
        audit["artifacts"] = {str(p.relative_to(out)): sha256(p) for p in sorted(out.rglob("*.json"))
                              if p.name != "run_manifest.json"}
        write(out / "run_manifest.json", audit)
        return audit
    except Exception as exc:
        audit["status"] = "FAILED"
        audit["error"] = type(exc).__name__ + ": " + str(exc)
        write(out / "run_manifest.json", audit)
        raise


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for k in ("match-json", "source-mp4", "out-dir"):
        p.add_argument("--" + k, required=True)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--causal-atoms-json", help="Historical development atom-fill only, requires --allow-dev")
    g.add_argument("--independent-atoms-json", help="Independent event-level annotations")
    p.add_argument("--allow-dev", action="store_true")
    p.add_argument("--video-id")
    p.add_argument("--score-left-team", choices=["team_1", "team_2"])
    p.add_argument("--score-mapping-provenance", help="How scoreboard column attribution was verified")
    p.add_argument("--expected-source-sha256")
    p.add_argument("--expected-events-sha256")
    p.add_argument("--expected-atom-source-sha256")
    p.add_argument("--template-id", action="append", help="Optional output filter; default all 8 + separate mixed hypothesis")
    return p


if __name__ == "__main__":
    run(parser().parse_args())
