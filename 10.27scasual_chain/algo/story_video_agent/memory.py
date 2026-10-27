"""观察记忆：复用 Video-RSI Initial Harness 的结构化 observation 列表形态。"""

from __future__ import annotations

from typing import Any, Dict, List


class Memory:
    """Store structured observations and action history."""

    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []

    def add(self, decision: Dict[str, Any], observation: Any) -> None:
        self.items.append(
            {
                "tool": decision.get("tool"),
                "arguments": decision.get("arguments", {}),
                "observation": observation,
            }
        )
