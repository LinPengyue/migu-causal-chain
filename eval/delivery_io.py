#!/usr/bin/env python3
"""交付_out / 上游事件 JSON 读写约定（9.31 共用）。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]


def _load_build_mod():
    path = ROOT / "scripts" / "build_datasets.py"
    spec = importlib.util.spec_from_file_location("cc_build_datasets", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def default_src_dir() -> Path:
    local = ROOT / "data" / "交付_out"
    if local.is_dir():
        return local
    return ROOT.parent / "causal_chain" / "examples" / "交付_out"


def safe_id_from_stem(stem: str) -> str:
    import re

    return re.sub(r"[^\w\-.]+", "_", stem)[:80]


def list_plain_jsons(src_dir: Path) -> List[Path]:
    """无 causal：上游事件识别输出。"""
    out: List[Path] = []
    for p in sorted(src_dir.glob("*.json")):
        if p.name.endswith("_causal.json"):
            continue
        out.append(p)
    return out


def list_causal_pairs(src_dir: Path) -> List[Tuple[str, Path, Path]]:
    """(stem, plain_path, causal_path)。"""
    pairs: List[Tuple[str, Path, Path]] = []
    for cau in sorted(src_dir.glob("*_causal.json")):
        stem = cau.name[: -len("_causal.json")]
        plain = src_dir / f"{stem}.json"
        if plain.exists():
            pairs.append((stem, plain, cau))
    return pairs


def load_plain_timeline(plain_path: Path) -> Tuple[str, List[Dict[str, Any]]]:
    mod = _load_build_mod()
    full = json.loads(plain_path.read_text(encoding="utf-8"))
    match_id = str(full.get("match_id") or plain_path.stem)
    timeline = mod.full_events_to_timeline(full)
    return match_id, timeline


def build_datasets_from_src(
    src_dir: Optional[Path] = None,
    *,
    quiet: bool = False,
) -> Dict[str, Any]:
    """调用 build_datasets.main；临时切换 SRC。"""
    import contextlib
    import io

    mod = _load_build_mod()
    src = Path(src_dir) if src_dir else default_src_dir()
    if not src.is_dir():
        raise FileNotFoundError(f"missing src: {src}")
    old = mod.SRC
    try:
        mod.SRC = src
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mod.main()
        text = buf.getvalue()
        if not quiet and text:
            print(text, end="" if text.endswith("\n") else "\n", flush=True)
        index_path = Path(mod.OUT) / "index.json"
        if index_path.exists():
            return json.loads(index_path.read_text(encoding="utf-8")).get("summary") or {}
        return {}
    finally:
        mod.SRC = old
