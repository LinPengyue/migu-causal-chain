# Phase 4B.4：对照 Video-RSI 官方模型调用（无计费）

**基准**: `6aee6fd` · **分支**: `story-va-phase2c`  
**官方源码**: [`solver_full_workspace/engine/services.py`](https://github.com/bingjunluo/Video-RSI/blob/main/solver_full_workspace/engine/services.py) — `PinnedProvider.chat()` / `Services._call("qwen")`  
**约束**: 离线配置 + Mock · **禁止真实计费** · 不自动兼容性实验

## 官方真实实现（摘要）

`PinnedProvider.chat` 请求体：

```python
{
  "model": request_model,
  "messages": messages,
  "temperature": config["temperature"],
  "max_tokens": model["max_tokens"],      # 官方配置常为 8192
  "thinking": {"type": "disabled"},
  "stream": False,
}
```

`qwen` 视觉：`prompt` 文本后，对每帧追加 `timestamp_seconds=<ts>` 文本，再跟 `image_url`（JPEG base64）。

## 本项目改动

| 项 | 行为 |
|----|------|
| `STORY_VLM_REQUEST_PROFILE=video_rsi` | 按角色启用兼容模式；**Planner 默认不变** |
| 温度 | VLM 默认可配置 **0**（`STORY_VLM_TEMPERATURE`） |
| `stream` | 显式 **`false`** |
| `thinking` | opt-in / video_rsi → `{"type":"disabled"}`；与 `enable_thinking`/`thinking_budget` **互斥** |
| `max_tokens` | 仍受项目 HTTP/Token/费用 cap；**禁止照搬 8192**；超限熔断保留 |
| 帧绑定 | `frame_id` + `actual_media_sec` 或 `requested_only`；禁止模型编造时间 |

## Paratera 文档

公开 API 示例含 `max_tokens`、`stream:false`，**未**记载 `thinking: {type: disabled}`。因此本阶段**只做离线/Mock**，不自动对 Paratera 发真实探测。

## 与 Phase 4B.2（3195 completion）假说

4B.2 发送了 `max_tokens=256`，但**未**发送 `thinking={type:disabled}`，也未落盘 `reasoning_tokens`/`finish_reason`。

**可能机制（未证实）**：若网关/模型默认开启隐藏思维链，而 `max_tokens` 只约束可见回复，则 `completion_tokens` 可能远大于 256（上游 Qwen 文档有类似区分；**Paratera 未证明**）。

**仍需真实 API 验证**：

1. Paratera 是否接受 `thinking={"type":"disabled"}`  
2. 接受后 `completion_tokens` 是否回落到 cap 附近  
3. `stream=false` / 帧时间绑定是否改变用量与观察质量  

## 产物

- 差异 JSON：`reports/phase4b4_video_rsi_request_diff.json`  
- Mock：`test_phase4b4_video_rsi.py`  
- 代码：`api_provider.py` / `vision_provider.py`  

**本阶段结束 · 无付费请求 · 未合并 main。**
