"""causal_chain8 入口：highlights | classify | strip | pipeline | extract | eval"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "用法:\n"
            "  python -m causal_chain8 highlights --timeline-json ... --out ...\n"
            "  python -m causal_chain8.build_highlights --timeline-json ... --out ...\n"
            "  python -m causal_chain8 classify --data ... --model-path ...\n"
            "  python -m causal_chain8 strip --timeline-json ... --model-path ... --out ...\n"
            "  python -m causal_chain8 match-highlight --strip-gold ... --out ..."
        )
        raise SystemExit(2)

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd in ("highlights", "build_highlights", "reel"):
        from causal_chain8.build_highlights import main as highlights_main

        sys.argv = [sys.argv[0]] + rest
        highlights_main()
        return

    if cmd == "classify":
        from causal_chain8.classify import main as classify_main

        classify_main(rest if rest else None)
        return

    if cmd == "strip":
        from causal_chain8.strip import main as strip_main

        strip_main(rest if rest else None)
        return

    if cmd in ("match-highlight", "link-strip", "highlight-chain"):
        from causal_chain8.build_match_highlight import main as match_hl_main

        match_hl_main(rest if rest else None)
        return

    if cmd in ("pipeline", "extract", "eval"):
        parser = argparse.ArgumentParser(description="causal_chain8")
        sub = parser.add_subparsers(dest="command", required=True)
        from causal_chain8.commands import register_eval, register_extract, register_pipeline

        register_pipeline(sub)
        register_extract(sub)
        register_eval(sub)
        args = parser.parse_args([cmd] + rest)
        args.func(args)
        return

    raise SystemExit(
        f"未知子命令: {cmd}（可用 highlights / classify / strip / pipeline / extract / eval）"
    )


if __name__ == "__main__":
    main()
