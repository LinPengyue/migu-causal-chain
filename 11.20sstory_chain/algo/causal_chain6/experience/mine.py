"""从 8.19_jiaofu 挖掘分层示范，并合成干扰变体（C）。"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Sequence

from causal_chain6.experience.noise import (
    SYNTH_INSERTABLE,
    has_interference,
    inject_interference,
    observed_interference,
)
from causal_chain6.mapping.presets import LABEL_ZH_TO_TEMPLATE
from causal_chain6.mapping.strategies import apply_mapping_chain
from causal_chain6.rules.robust import normalize_types

SKIP_TEMPLATES = {"outcome_other"}
CAP_PER_TEMPLATE = 8
MIN_LEN = 3
MAX_LEN = 10


def _types_from_chain(row: Dict[str, Any]) -> List[str]:
    try:
        pack, _ = apply_mapping_chain(row, mapping_spec="params_first+annotation_compat", index=0)
    except ValueError:
        return []
    return [str(e.get("type", "")) for e in pack.get("events_normalized") or [] if e.get("type")]


def mine_and_synthesize(
    jiaofu_path: Path,
    *,
    cap: int = CAP_PER_TEMPLATE,
) -> List[Dict[str, Any]]:
    doc = json.loads(jiaofu_path.read_text(encoding="utf-8"))
    chains = doc.get("causal_chains") or []
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    all_types: List[List[str]] = []

    for chain in chains:
        lab = str(chain.get("causal_chain_subtype") or chain.get("chain_template_id") or "").strip()
        tid = LABEL_ZH_TO_TEMPLATE.get(lab, "")
        if not tid or tid in SKIP_TEMPLATES:
            continue
        types = _types_from_chain(chain)
        types = normalize_types(types)
        if not (MIN_LEN <= len(types) <= MAX_LEN):
            continue
        all_types.append(types)
        inter = has_interference(types)
        buckets[tid].append(
            {
                "chain_template_id": tid,
                "types": types,
                "source": "jiaofu_interference" if inter else "jiaofu_clean",
                "has_interference": inter,
                "n": len(types),
            }
        )

    observed = observed_interference(all_types)
    exemplars: List[Dict[str, Any]] = []
    for tid, items in buckets.items():
        items.sort(key=lambda x: (0 if x["has_interference"] else 1, -min(x["n"], 8), x["n"]))
        chosen = items[:cap]
        exemplars.extend(chosen)
        # C：对干净主链插入交付中真实出现过的噪声
        synth_n = 0
        for ex in chosen:
            if ex["has_interference"] or synth_n >= 2:
                continue
            for noise in SYNTH_INSERTABLE:
                if noise not in observed:
                    continue
                syn_types = inject_interference(ex["types"], noise, at="mid")
                if syn_types == ex["types"]:
                    continue
                exemplars.append(
                    {
                        "chain_template_id": tid,
                        "types": syn_types,
                        "source": f"synth_{noise}",
                        "has_interference": True,
                        "n": len(syn_types),
                    }
                )
                synth_n += 1
                break

    return exemplars


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    src = root / "causal_chain" / "examples" / "8.19_jiaofu.json"
    out = Path(__file__).resolve().parent / "data" / "exemplars.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    items = mine_and_synthesize(src)
    payload = {
        "description": "chain6 few-shot：8.19 分层示范 + 交付噪声合成，不含 special_cc 序列",
        "n": len(items),
        "exemplars": items,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out} n={len(items)}")


if __name__ == "__main__":
    main()
