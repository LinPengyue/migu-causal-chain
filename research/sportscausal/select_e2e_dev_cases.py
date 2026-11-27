"""Choose development cases from frozen FanEdit v1.1, NOT an inference input.

Print only match/source-level inventory (no reference story IDs, event IDs,
segments, scores, or titles). Candidate selection is a development exposure.
Never auto-pick a source by filename when it is ambiguous. The native runner
still requires separately verified same-video/event/supplement provenance.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "validation" / "fanedit_v1_1_e2e_registry.json"
FROZEN_SHA256 = {
    "story_chains.jsonl": "78fd0ec8bb95f6926f3334b9446364f41bc13f32de81ec287e07eb34c76c4350",
    "matches.jsonl": "50cf992921ca6576b0c41e59968ae9d42f3b727db5a16edfa1724e869b8b73c3",
    "videos.jsonl": "86568db1776bd44b4b1619f7f3c9aa7fcc65d01c801bc998efdcb972f04577e1",
}
PENDING = ("alternating_threats", "equalization", "lead_preservation",
           "threat_phase_change", "set_piece_breakthrough", "turnover_to_goal")


def rows(path):
    return [json.loads(s) for s in path.read_text(encoding="utf-8-sig").splitlines() if s.strip()]


def normalized(name):
    return re.sub(r"[\s_]+", "", unicodedata.normalize("NFKC", Path(name).name)).casefold()


def inventory(benchmark, video_roots, registry):
    for name, digest in FROZEN_SHA256.items():
        actual = hashlib.sha256((benchmark / name).read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError("not frozen FanEdit v1.1: " + name)
    matches = {m["match_id"]: m for m in rows(benchmark / "matches.jsonl")}
    videos = {v["video_id"]: v for v in rows(benchmark / "videos.jsonl")}
    stories = rows(benchmark / "story_chains.jsonl")
    if len(matches) != 84 or len(videos) != 105 or len(stories) != 173:
        raise ValueError("unexpected frozen inventory counts")
    paths = {}
    for root in video_roots:
        if not root.is_dir():
            raise ValueError("video root not found: " + str(root))
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() == ".mp4":
                paths.setdefault(normalized(p.name), set()).add(str(p.resolve()))
    known = {r["match_id"] for r in registry["dev_exposure"]}
    mapping = {r["template_id"]: (r["category"], r["subtype"]) for r in registry["templates"]}
    output = {}
    for tid in PENDING:
        cat, sub = mapping[tid]
        cases = {}
        for s in stories:
            if (s["category"], s["subtype"]) != (cat, sub):
                continue
            mid = s["match_id"]
            m = matches[mid]
            # Current R3 only accepts one source. Do not combine two halves or
            # assume that equal file names establish equal source time axes.
            vids = set(seg["video_id"] for seg in s["segments"])
            if len(m["video_ids"]) != 1 or vids != set(m["video_ids"]):
                continue
            vid = next(iter(vids))
            v = videos[vid]
            candidates = sorted(paths.get(normalized(v["video_name"]), set()))
            cases[mid] = {
                "match_id": mid, "match_name": m["match_name"], "video_id": vid,
                "reference_video_name": v["video_name"],
                "source_event_path": v["source_event_path"],
                "candidate_local_paths": candidates,
                "media_status": ("UNIQUE_NAME_MATCH_UNVERIFIED" if len(candidates)==1 else
                                 "AMBIGUOUS_NAME_MATCH" if candidates else "NOT_FOUND"),
                "already_development_exposed": mid in known or m.get("development_exposure")=="known_development",
                "identity_verified": False,
                "formal_eval_eligible": False,
            }
        # Reuse known development exposure where possible, not a test holdout.
        # Report all alternatives; no candidate selection based on gold clip timing.
        output[tid] = sorted(cases.values(), key=lambda c: (
            c["media_status"] != "UNIQUE_NAME_MATCH_UNVERIFIED",
            not c["already_development_exposed"], c["match_id"]))
    return {
        "schema": "sportscausal_fanedit_dev_case_inventory_v1",
        "benchmark_ref": registry["fanedit"]["ref"],
        "scope": "offline reference-conditioned case selection only; never pass this inventory to inference",
        "candidates": output,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--benchmark-dir", type=Path, required=True)
    p.add_argument("--video-root", type=Path, action="append", required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    result = inventory(a.benchmark_dir, a.video_root, registry)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    for tid, cases in result["candidates"].items():
        unique = sum(c["media_status"]=="UNIQUE_NAME_MATCH_UNVERIFIED" for c in cases)
        print(f"{tid}: {len(cases)} single-source reference matches, {unique} unique filename matches")


if __name__ == "__main__":
    main()
