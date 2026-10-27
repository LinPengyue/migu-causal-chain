"""FastAPI 入口：咪咕故事链集锦 2.3–2.5 入站；2.6 为出站回调。

第一版必须单 worker（内存 TaskManager）：

    export PYTHONPATH=$PWD/algo:$PWD
    uvicorn api.app:app --host 0.0.0.0 --port 8000 --workers 1
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "algo")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from api.schemas import (  # noqa: E402
    ApiResponse,
    EndRequest,
    StartRequest,
    SyncRequest,
    TaskDebugView,
)
from api.service import SERVICE  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

app = FastAPI(
    title="清华AI服务 · 故事链集锦协议层",
    description=(
        "咪咕 2.3–2.6 RC（单 worker）。"
        "eventTime/start/end=媒体时间轴秒；算法内部毫秒。"
        "highlightType=5 → chainType=19 集锦组合链。"
        "eventTypeId 映射见 api/event_type_map.py（正式字典待咪咕确认）。"
        "正式接口：POST /highlight/start|sync|end。"
    ),
    version="0.4.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "workers_required": 1}


@app.post("/highlight/start", response_model=ApiResponse)
def highlight_start(req: StartRequest) -> ApiResponse:
    code, message = SERVICE.start(req.taskId, req.matchId, req.callbackUrl)
    return ApiResponse(code=code, message=message)


@app.post("/highlight/sync", response_model=ApiResponse)
def highlight_sync(req: SyncRequest) -> ApiResponse:
    code, message = SERVICE.sync(req.taskId, req.matchId, req.clip.model_dump())
    return ApiResponse(code=code, message=message)


@app.post("/highlight/end", response_model=ApiResponse)
def highlight_end(req: EndRequest) -> ApiResponse:
    code, message = SERVICE.end(req.taskId, req.matchId)
    return ApiResponse(code=code, message=message)


# 调试接口默认关闭；仅 DEBUG=true 时注册
if os.environ.get("DEBUG", "").lower() in ("1", "true", "yes"):

    @app.get("/debug/task/{task_id}", response_model=TaskDebugView, include_in_schema=False)
    def debug_task(task_id: str):
        snap = SERVICE.debug_task(task_id)
        if snap is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="task not found")
        return TaskDebugView(
            task_id=snap["task_id"],
            match_id=snap["match_id"],
            status=snap["status"],
            n_events=snap["n_events"],
            n_clip_ids=snap["n_clip_ids"],
            n_results=snap["n_results"],
            callback_records=snap.get("callback_records") or [],
        )
