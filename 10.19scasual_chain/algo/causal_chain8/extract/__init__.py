"""延迟加载 extract_causal_events，避免 import 环。"""

from __future__ import annotations

from causal_chain8.io.extraction_result import ExtractionResult

__all__ = ["ExtractionResult", "extract_causal_events"]


def extract_causal_events(*args, **kwargs):
    from causal_chain8.extract.core import extract_causal_events as _fn

    return _fn(*args, **kwargs)
