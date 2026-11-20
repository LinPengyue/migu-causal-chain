"""Offline Phase10 evaluation CLI; never runs VLMs or changes delivery BEST.

Examples:
  PYTHONPATH=algo python -m story_video_agent_v3.story_quality_cli validate-chain \
      --input human_story_chain.json --out chain_validation.json
  PYTHONPATH=algo python -m story_video_agent_v3.story_quality_cli blind-pair \
      --reviews sealed_reviews.json --allocation unblind_after_rating.json \
      --gates independent_g0_audit.json --out human_pair_result.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .story_chain_annotation import validate_long_story_chain
from .story_quality_protocol import evaluate_blind_story_pair


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, content: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase10 offline Benchmark/quality evaluation")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-chain")
    validate.add_argument("--input", type=Path, required=True)
    validate.add_argument("--out", type=Path, required=True)
    compare = commands.add_parser("blind-pair")
    compare.add_argument("--reviews", type=Path, required=True)
    compare.add_argument("--allocation", type=Path, required=True)
    compare.add_argument("--gates", type=Path, required=True)
    compare.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-chain":
            result = validate_long_story_chain(_read(args.input))
            _write(args.out, result)
            print(result["valid"], "errors:", len(result["errors"]))
            return 0 if result["valid"] else 2
        result = evaluate_blind_story_pair(
            _read(args.reviews), _read(args.allocation), _read(args.gates),
        )
        _write(args.out, result)
        print(result["decision"], "promotion_auto_disabled")
        return 0
    except (ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(f"Phase10 evaluation FAILED CLOSED: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
