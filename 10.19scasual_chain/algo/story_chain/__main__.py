"""导出逆风翻盘故事链。

在 algo 目录执行：

  python -m story_chain --deliver-dir ../data/交付_out --out-dir ../reports/story_t01
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from story_chain.end_to_end import run_paths


def _stem(path: Path) -> str:
    name = path.name
    if name.endswith("_causal.json"):
        return name[: -len("_causal.json")]
    return path.stem


def build_one(events_path: Path, causal_path: Path) -> dict:
    return run_paths(events_path, causal_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="按比分轨迹导出逆风翻盘故事链")
    parser.add_argument("--events", type=Path, help="单场全量事件 JSON")
    parser.add_argument("--causal", type=Path, help="单场因果链 JSON")
    parser.add_argument("--deliver-dir", type=Path, help="交付目录，成对读取 *.json 与 *_causal.json")
    parser.add_argument("--out", type=Path, help="单场输出路径")
    parser.add_argument("--out-dir", type=Path, help="批量输出目录")
    args = parser.parse_args()

    if args.events and args.causal:
        story = build_one(args.events, args.causal)
        if args.out is None:
            raise SystemExit("单场导出需要 --out")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
        label = "story" if story["has_story"] else ("candidate" if story.get("is_candidate") else story["no_story_reason"])
        print(args.out, label, "events", len(story["events"]))
        return

    if args.deliver_dir is None or args.out_dir is None:
        raise SystemExit("需要 --events/--causal/--out，或 --deliver-dir/--out-dir")

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    index = []
    causal_paths = sorted(args.deliver_dir.glob("*_causal.json"))
    for causal_path in causal_paths:
        events_path = causal_path.with_name(_stem(causal_path) + ".json")
        if not events_path.is_file():
            continue
        story = build_one(events_path, causal_path)
        out_path = out_dir / f"{_stem(causal_path)}.json"
        out_path.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
        index.append(
            {
                "file": out_path.name,
                "match_id": story.get("match_id"),
                "has_story": story["has_story"],
                "is_candidate": story.get("is_candidate", False),
                "story_tier": story.get("story_tier", "none"),
                "story_label_zh": story["story_label_zh"],
                "no_story_reason": story["no_story_reason"],
                "protagonist_side": story["protagonist_side"],
                "score_path": [node["score"] for node in story["score_path"]],
                "n_events": len(story["events"]),
                "roles": [row["story_role"] for row in story["events"]],
            }
        )
    index_path = out_dir / "_index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    n_story = sum(1 for row in index if row["has_story"])
    n_cand = sum(1 for row in index if row.get("is_candidate"))
    print(f"matches {len(index)} story {n_story} candidate {n_cand} index {index_path}")


if __name__ == "__main__":
    main()
