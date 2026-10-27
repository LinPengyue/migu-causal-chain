# Phase 4B.3：Qwen 输出 Token 限额兼容性审计（无计费）

**基准**: `ea30c3f` · **分支**: `story-va-phase2c`  
**约束**: 仅代码/文档/Mock · **禁止** `/chat/completions` 真实计费

## 1. Phase 4B.2 请求构造核查

代码路径（当时）：`ApiProvider._post_chat` 在 `STORY_API_TOKEN_PARAM` 默认 `max_tokens` 且 `max_completion_tokens` 生效时，向 body 写入：

```json
{ "model": "Qwen3.6-Plus", "max_tokens": 256, "temperature": ..., "messages": [...] }
```

预检记录印证：`token_param=max_tokens`，`effective max_completion_tokens=256`，`sends_both_token_params=false`。

**结论**：客户端**确实发送了** `max_tokens=256`（构造正确）。服务商回报 `completion_tokens=3195` 说明**限额未被服务端按预期约束**（或 thinking/其它不可见输出计入 completion，而旧报告无法区分）。

本阶段 Mock 复现：`test_phase4b2_style_sends_max_tokens_256` 通过。

## 2. Paratera vs 上游文档（不得等同）

| 来源 | `max_tokens` | `max_completion_tokens` | `enable_thinking` / `thinking_budget` |
|------|--------------|-------------------------|----------------------------------------|
| **Paratera 公开 API 文档**（useApi） | 示例中使用 | **未列出** | **未列出** |
| 阿里云 / QwenCloud 等（上游参考） | 思考模式下语义/上限特殊；建议改用 completion | 限制含思维链的总输出 | 有；默认 thinking 可能开启 |

**审计立场**：不以阿里云文档直接假定 Paratera 行为。默认**只发送** Paratera 示例已出现的 `max_tokens`。Thinking 相关字段改为 **opt-in**（`STORY_VLM_SEND_THINKING=1` 等）后才附加，调用方自担兼容风险。

## 3. 旧响应字段（不可恢复）

对 `_local_render/phase4b_real_vlm2/phase4a_experiment_report.json` 全树扫描：

| 字段 | 状态 |
|------|------|
| `usage.completion_tokens` | 有（3195） |
| `usage.completion_tokens_details.reasoning_tokens` | **无** |
| `choices[0].finish_reason` | **无**（当时未落盘） |
| `message.reasoning_content` | **无** |

**明确声明**：上述缺失字段**不可从旧报告恢复**；本阶段不推断、不伪造。新代码将在未来真实响应中记录脱敏审计（见下），且**永不保存** `reasoning_content` 原文。

## 4. 代码改动摘要

- **按角色** Token 字段 / 输出预算：`STORY_VLM_TOKEN_PARAM`、`STORY_PLANNER_TOKEN_PARAM`、`STORY_*_MAX_COMPLETION_TOKENS`
- **Thinking 配置**独立存在；默认不发送；仅 `STORY_*_SEND_THINKING=1` 时发送明确设置的 `enable_thinking` / `thinking_budget`
- 脱敏审计：`request_token_param`、limit、`finish_reason`、`reasoning_tokens`（若有）、`visible_output_chars`、`output_budget_exceeded`
- **超限阻断**：若回报 `completion_tokens >` 配置预算，标记异常并**阻断后续真实 HTTP**；不改写供应商用量，费用仍为估算
- 搜索窗 provenance：区分 `observed_best_window` vs `proposed_next_window`

## 5. shrink vs EDL（非精细定位完成）

Phase 4B.2：

| 项 | 值 |
|----|-----|
| 本轮**已观察**窗 | **3059.903–3071.903**（写入 candidate / EDL） |
| 规则 **shrink** `next_window` | **3062.903–3068.903** |
| `max_rounds` | **1** → next_window **未再抽帧验证** |

因此 EDL 对齐的是**当前观察候选窗**，不是 shrink 建议。**不能**把 3062.9–3068.9 报成「已精细定位」。新字段：`window_provenance` / `not_fine_localized`。

## 6. Mock 测试

`PYTHONPATH=algo python -m unittest story_video_agent.test_phase4b3_token_audit` — 全部通过（参数兼容、计数、超限阻断、角色隔离、shrink 区分）。

## 7. 后续建议（不自动付费）

1. 新授权联调时为 VLM 显式试 `STORY_VLM_TOKEN_PARAM=max_completion_tokens`（若 Paratera 拒参则回退）。  
2. 需要压 thinking 时，仅在确认兼容后设 `STORY_VLM_SEND_THINKING=1` + `ENABLE_THINKING=0` 或预算。  
3. 精细定位需 `max_rounds≥2` 以**执行并观察** shrink 窗，或人工核验 3065.9 邻域。

**本阶段结束 · 无付费请求。**
