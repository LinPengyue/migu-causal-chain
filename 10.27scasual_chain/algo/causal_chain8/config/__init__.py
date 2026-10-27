"""加载 chain4 profile 配置（JSON）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def load_profile(name_or_path: str) -> Dict[str, Any]:
    p = Path(name_or_path)
    if not p.suffix:
        p = Path(__file__).resolve().parent / f"{name_or_path}.json"
    if not p.is_file() and not Path(name_or_path).is_absolute():
        alt = Path(__file__).resolve().parent / Path(name_or_path).name
        if alt.is_file():
            p = alt
    if not p.is_file():
        raise FileNotFoundError(f"profile not found: {name_or_path}")
    return json.loads(p.read_text(encoding="utf-8"))
