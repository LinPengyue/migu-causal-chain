# Phase 4B.5：Video-RSI 请求格式真实兼容性验证

**基准**: `story-va-phase2c` @ `47685f1`  
**授权**: 最多 **1** 次真实 HTTP · 已用尽并停止 · 无重试  
**输出目录**: `_local_render/phase4b5_rsi_compat/`（本地；未提交帧/视频）

## 结论

Paratera `Qwen3.6-Plus` **接受** Video-RSI 风格请求：

- `temperature=0`
- `thinking={"type":"disabled"}`
- `stream=false`
- `max_tokens=256`

HTTP **200** · 尝试次数 **1/1** · `completion_tokens=218`（≤256）· `finish_reason=stop` · **未**超限熔断。  
相对 Phase 4B.2 的 **3195** completion tokens，关闭 Thinking 后用量回落到 cap 内，**强烈支持**「默认隐藏思维链计入 completion」假说（仍非账单证明）。

视觉 JSON **完整合法**（`normalized_ok=true`），识别 **shot + celebration**，叙述暗示扳平进球；记分牌仍 0–1（与 4B.2 类似的转播延迟说明）。`observation_only`；`render_ready=false`；go_ahead unresolved。

## 请求确认

运行前构造校验（同进程配置）：

| 字段 | 值 |
|------|-----|
| profile | `video_rsi` |
| model | `Qwen3.6-Plus` |
| temperature | 0.0 |
| max_tokens | 256 |
| thinking | `{"type":"disabled"}` |
| stream | false |
| enable_thinking / thinking_budget | **未发送**（互斥） |
| max_retries | 0 |
| STORY_API_MAX_CALLS | 1 |

采样：3059.96 / **3065.9** / 3071.86 s（与预期一致）。

## Token / 审计

| 项 | 4B.2 | **4B.5** |
|----|------|----------|
| thinking disabled | 否 | **是** |
| HTTP | 1（成功） | **1**（成功） |
| prompt_tokens | 6427 | 6505 |
| completion_tokens | **3195** | **218** |
| total_tokens | 9622 | 6723 |
| finish_reason | （旧报告未存） | **stop** |
| reasoning_tokens | 不可恢复 | **null**（服务商未提供 details） |
| output_budget_exceeded | （当时无熔断逻辑） | **false** |
| est_cost_usd（估算） | ≈0.00288 | ≈**0.00111** |

未出现 JSON 截断迹象；若 `finish_reason=length` 且 `normalized_ok=false` 才应记「输出预算过小」，本次不适用。

## 观察摘要（脱敏）

- actions: `shot`, `celebration`
- relation: 禁区内射门后立即滑跪庆祝，暗示扳平
- notes: f_0001 射门；f_0002 庆祝；比分牌仍 0–1
- labels primary: `shot` · confidence 0.95 · `fact_verified=false`

## 门禁

- go_ahead_goal: pending / blocked  
- `render_ready=false` · 未跑 preview（`--no-render`）  
- `not_fine_localized=true`（shrink next_window 未执行）

## 产物

- `reports/phase4b5_video_rsi_real_compat.md`（本文件）
- `reports/phase4b5_video_rsi_real_compat.json`
- `reports/phase4b5_preflight.json`
- 本地完整实验：`_local_render/phase4b5_rsi_compat/phase4a_experiment_report.json`

**本次实验结束 · 无第二次 HTTP · 未进入其他付费实验。**
