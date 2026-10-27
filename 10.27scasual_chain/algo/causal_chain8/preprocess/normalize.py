"""构建 EvalRecord（经 pipeline 抽取 + 分类）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from causal_chain8.io.eval_record import EvalRecord
from causal_chain8.pipeline import pipeline_to_eval_records, run_pipeline_file


def build_eval_records(
    input_path: Path,
    *,
    profile: Dict[str, Any],
    model=None,
    processor=None,
    device: str = "cuda",
    video_root: str | None = None,
    limit: int = 0,
) -> List[EvalRecord]:
    results = run_pipeline_file(
        input_path,
        profile=profile,
        model=model,
        processor=processor,
        device=device,
        video_root=video_root,
        limit=limit,
    )
    return pipeline_to_eval_records(results, profile=profile)
