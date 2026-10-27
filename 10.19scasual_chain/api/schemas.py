"""咪咕 2.3–2.6 请求/响应 Pydantic 模型。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    code: str = "0"
    message: str = "success"


class StartRequest(BaseModel):
    taskId: str = Field(..., min_length=1)
    matchId: str = Field(..., min_length=1)
    callbackUrl: str = Field(..., min_length=1)


class ClipPayload(BaseModel):
    """咪咕 2.5 拆条同步 clip：除 score 外均为必填。"""

    clipId: str = Field(..., min_length=1)
    videoPath: str = Field(..., min_length=1)
    eventName: str = Field(..., min_length=1)
    eventTypeId: str = Field(..., min_length=1)
    eventTime: float = Field(
        ...,
        description="媒体时间轴秒（可小数）；原点=输入视频/直播会话起点（含片头/中场等）。内部转为毫秒。",
    )
    score: Optional[Any] = None


class SyncRequest(BaseModel):
    taskId: str = Field(..., min_length=1)
    matchId: str = Field(..., min_length=1)
    clip: ClipPayload


class EndRequest(BaseModel):
    taskId: str = Field(..., min_length=1)
    matchId: str = Field(..., min_length=1)


class HighlightItem(BaseModel):
    clipId: str
    start: float = Field(..., description="媒体时间轴秒")
    end: float = Field(..., description="媒体时间轴秒")


class CallbackBody(BaseModel):
    taskId: str
    matchId: str
    highlightType: int = Field(..., description="1~4 因果链大类；5=赛后集锦组合链")
    chainType: int = Field(..., description="1~18 模板；highlightType=5 时固定 19")
    highlights: List[HighlightItem]


class TaskDebugView(BaseModel):
    task_id: str
    match_id: str
    status: str
    n_events: int
    n_clip_ids: int
    n_results: int
    callback_records: List[Dict[str, Any]] = Field(default_factory=list)
