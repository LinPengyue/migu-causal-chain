"""Zero-HTTP P10-B graph preview from an existing V3-R EDL and plan.

No raw video frames, no model calls, no benchmark gold. Does not edit EDL.
Example:
  PYTHONPATH=algo python -m story_video_agent_v3.story_inferred_graph_cli \
      --edl 04_phase5/candidate_edl.json --story-plan 04_phase5/story_plan.json \
      --out phase10b/agent_narrative_graph.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .story_inferred_narrative_graph import (
    build_inferred_narrative_graph,
    graph_observation_targets,
)
from .story_timeline import edl_rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Offline Agent narrative graph preview")
    p.add_argument("--edl", type=Path, required=True)
    p.add_argument("--story-plan", type=Path, required=True)
    p.add_argument("--source-sha256", type=str, default=None)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        edl_doc = json.loads(args.edl.read_text(encoding="utf-8"))
        edl = edl_rows(edl_doc)
        if not edl:
            raise ValueError("no EDL segments available")
        plan = json.loads(args.story_plan.read_text(encoding="utf-8"))
        graph = build_inferred_narrative_graph(
            edl=edl, story_plan=plan, source_sha256=args.source_sha256,
        )
        graph["observation_targets"] = graph_observation_targets(graph, max_targets=2)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("nodes:", graph["summary"]["node_count"],
              "event/short-chain links:", graph["summary"]["event_or_short_chain_reference_links"],
              "review targets:", len(graph["observation_targets"]))
        return 0
    except (ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(f"Failed closed: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
