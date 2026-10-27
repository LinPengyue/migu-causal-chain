# Phase 4A VLM-only 小规模联调方案（无自动执行）

**状态**: 准备就绪 · **默认不计费** · 须用户明确授权后才可 `--real`

## 目标

在克罗地亚真实比赛视频上，用 **少量真实采样帧** 调用 VLM，验证：

- HTTP 限额与重试计数
- 结构化观察（frame_id、媒体时间、标签、不确定性）
- **不**自动成片；go_ahead 保持 unresolved；`render_ready=false`；`final` 硬拒绝

## 前置门控

```bash
export STORY_API_ENABLE=1
export STORY_PHASE4A_REAL=1          # Phase 4A 显式授权
export STORY_API_SMOKE=1
export STORY_LLM_BASE_URL=...        # 或 OPENAI_BASE_URL
export STORY_LLM_API_KEY=...         # 勿写入仓库
export STORY_VLM_MODEL=...           # 视觉模型
export STORY_API_MAX_CALLS=3         # 建议：最多 3 次 HTTP（含失败/429 重试）
export STORY_API_MAX_COST_USD=0.10   # 估算软顶，≠ 账单绝对上限
export STORY_API_MAX_COMPLETION_TOKENS=256
export STORY_API_TOKEN_PARAM=max_tokens   # 或 max_completion_tokens / none
# 若需生产成片授权（本联调不需要）：
# export STORY_INTERNAL_VERIFY_KEY='long-random-secret'
```

`est_cost_usd` 仅为本地单价估算，**不是**发票硬上限。

## 推荐参数（equalizer 优先）

| 项 | 建议 |
|----|------|
| 视频 | `/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4` |
| Story | `reports/story_t01/2022-11-28 克罗地亚vs加拿大.json` |
| Plan | `reports/story_compose_phase3a1_croatia.json` |
| 模式 | `vlm-only` |
| 目标 | 先 `equalizer_goal`（seed≈3065.9s）；**不要**为凑结果 Mock 抬升 go_ahead |
| 抽帧 | `--frames-per-round 2 --max-rounds 1 --frame-budget 4` |
| HTTP | `STORY_API_MAX_CALLS=3`（与代码默认 12 取 **min** → 生效 3） |

## Dry-check（不计费，先跑）

```bash
cd /tmp/migu-va2c/10.27scasual_chain   # 或仓库内对应路径
PYTHONPATH=algo python -m story_video_agent.phase4a_optimize \
  --story-json "reports/story_t01/2022-11-28 克罗地亚vs加拿大.json" \
  --video-path "/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4" \
  --out-dir _local_render/phase4a_dry \
  --mode vlm-only \
  --dry-check
```

检查输出中的：

- `effective_caps.max_calls / max_cost_usd / max_completion_tokens`
- `models.vision` / `vendor_compat.token_param`
- `verify_key_persistent`
- **不得**出现 API Key 明文

## 授权后真实运行（人工执行，本阶段脚本不自动跑）

```bash
PYTHONPATH=algo python -m story_video_agent.phase4a_optimize \
  --story-json "reports/story_t01/2022-11-28 克罗地亚vs加拿大.json" \
  --video-path "/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4" \
  --plan-json reports/story_compose_phase3a1_croatia.json \
  --out-dir _local_render/phase4a_vlm_only \
  --mode vlm-only \
  --real \
  --max-rounds 1 \
  --frames-per-round 2 \
  --frame-budget 4 \
  --v1-summary _local_render/phase3b/croatia_preview_summary.json
```

## 期望产物

- `phase4a_experiment_report.json`：原始/结构化 VLM、`frame_id`、`requested/actual_media_sec`、错误与 `http_attempts`
- preview 可选；**不得** `render_ready=true`
- go_ahead 仍 unresolved / placeholder
- `final` 模式继续硬拒绝

## 禁止项

- 用 Mock / 伪造 `granted_by` / 模型 goal 标签绕过门禁
- `attest_semantic_result(passed)` 当作「已视觉核实进球」
- 未设 `STORY_INTERNAL_VERIFY_KEY` 时做生产成片授权
- 自动扩大 HTTP 次数绕过 `STORY_API_MAX_CALLS`
