"""Offline forensic comparison of historical story EDLs.

Read-only; does not infer that a candidate or BEST was actually rendered.
Input: manifest JSON {"versions":[{"name":"...", "edl_path":"...",
"video_path":"..." (optional), "run_manifest_path":"..." (optional)}]}.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .story_timeline import edl_rows, active_cut_rows


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize(edl):
    rows = active_cut_rows(edl_rows(edl))
    return [{
        "segment_id": str(r.get("segment_id") or ""),
        "role": r.get("role"), "beat": r.get("beat"),
        "media_in": r.get("media_in"), "media_out": r.get("media_out"),
        "event_ids": r.get("event_ids") or [],
        "first_live_status": r.get("first_live_status"),
    } for r in rows]


def compare(left, right):
    a = {r["segment_id"]: r for r in left if r["segment_id"]}
    b = {r["segment_id"]: r for r in right if r["segment_id"]}
    common = a.keys() & b.keys()
    return {
        "added_ids": sorted(b.keys() - a.keys()),
        "removed_ids": sorted(a.keys() - b.keys()),
        "changed": [{"segment_id": k, "before": a[k], "after": b[k]}
                    for k in sorted(common) if a[k] != b[k]],
        "unchanged_count": sum(a[k] == b[k] for k in common),
        "warning": "ID-based comparison; renamed segments or shifted source windows need manual identity review",
    }


def audit(manifest, root):
    versions = []
    for v in manifest["versions"]:
        path = (root / v["edl_path"]).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        rows = normalize(json.loads(path.read_text(encoding="utf-8")))
        if not rows:
            raise ValueError("empty_or_unrecognized_edl:" + str(path))
        entry = {"name": v["name"], "edl_path": str(path),
                 "edl_sha256": digest(path), "segment_count": len(rows),
                 "rows": rows, "video": None, "run_manifest": None}
        for key, target in (("video_path", "video"), ("run_manifest_path", "run_manifest")):
            if v.get(key):
                p = (root / v[key]).resolve()
                entry[target] = {"path": str(p), "exists": p.is_file(),
                                 "sha256": digest(p) if p.is_file() else None}
        versions.append(entry)
    return {
        "schema": "v3a_story_edl_lineage_audit_v1",
        "status": "FORENSIC_ONLY_NOT_PROOF_OF_RENDER_BINDING",
        "versions": versions,
        "comparisons": [
            {"from": a["name"], "to": b["name"],
             **compare(a["rows"], b["rows"])}
            for a, b in zip(versions, versions[1:])
        ],
        "requirements": [
            "Verify video-to-EDL binding using original run manifests and hashes",
            "Compare segment identity by event and source window, not only segment_id",
            "Do not assume latest EDL is BEST or complete story",
            "Identify candidate-vs-accepted revisions and rollback records",
            "Never use historical human gold as formal E2E model input",
        ],
        "api_calls": 0, "edl_modified": False, "video_modified": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError("refuse_overwrite_existing_report")
    source = json.loads(args.manifest.read_text(encoding="utf-8"))
    result = audit(source, args.manifest.resolve().parent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "versions": len(result["versions"]), "api_calls": 0}))


if __name__ == "__main__":
    main()
