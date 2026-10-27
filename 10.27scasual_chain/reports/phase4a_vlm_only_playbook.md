# Phase 4A VLM-only 小规模联调方案（无自动执行）

**状态**: Phase 4A.1 预检就绪 · **默认不计费** · 须用户明确授权后才可 `--real`（本仓库脚本不自动跑）

## 目标

在克罗地亚真实比赛视频上，用 **少量真实采样帧** 调用 VLM，验证：

- HTTP 限额与重试计数
- 结构化观察（frame_id、媒体时间、标签、不确定性）
- **不**自动成片；go_ahead 保持 unresolved；`render_ready=false`；`final` 硬拒绝

## Video-RSI 官方双模型

| 角色 | 官方标签 | 环境变量 | 说明 |
|------|----------|----------|------|
| Planner | `deepseek-v4-pro` | `STORY_LLM_MODEL` | vlm-only 模式不调用 Planner |
| VLM | `qwen3.6-plus` | `STORY_VLM_MODEL` | **实际 request_model 以服务商可用 ID 为准** |

## 首次真实联调固定配置

| 项 | 固定值 |
|----|--------|
| 视频 | `/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4` |
| Story | `reports/story_t01/2022-11-28 克罗地亚vs加拿大.json` |
| Plan | `reports/story_compose_phase3a1_croatia.json` |
| 模式 | `vlm-only` |
| 目标 | **仅** `--targets equalizer_goal`（seed≈**3065.903s** 原始候选窗） |
| 轮次/帧 | 建议 `--max-rounds 1 --frames-per-round 3 --frame-budget 4`（n=2 仅两端；n=3 含中心 **3065.903s**） |
| HTTP | `STORY_API_MAX_CALLS=3`（含失败/429；与代码显式值取 **min**） |
| 输出 Token | `STORY_API_MAX_COMPLETION_TOKENS=256` |
| 费用 | 遵守用户 `STORY_API_MAX_COST_USD`；**仅为估算，≠ 账单绝对上限** |
| 网络 | 须可 DNS 出网；Agent 沙箱/`full_network` 可能 `URLError`/`gaierror`（见 phase4b1 排障） |

不指定 `--targets` 时默认 `equalizer_goal` + `go_ahead_goal`（向后兼容）。首次真实联调**必须**显式 `--targets equalizer_goal`，避免无关 HTTP。

## 前置门控

```bash
export STORY_API_ENABLE=1
export STORY_PHASE4A_REAL=1
export STORY_API_SMOKE=1
export STORY_LLM_BASE_URL=...        # 或 OPENAI_BASE_URL
export STORY_LLM_API_KEY=...         # 勿写入仓库
export STORY_LLM_MODEL=deepseek-v4-pro   # 或服务商等价 ID
export STORY_VLM_MODEL=qwen3.6-plus      # 或服务商等价 ID
export STORY_API_MAX_CALLS=3
export STORY_API_MAX_COST_USD=0.10   # 估算软顶
export STORY_API_MAX_COMPLETION_TOKENS=256
export STORY_API_TOKEN_PARAM=max_tokens   # 或 max_completion_tokens / none
```

## Dry-check（不计费，先跑；可带 --real 仅预检）

```bash
cd /tmp/migu-va2c/10.27scasual_chain   # 或仓库内对应路径
PYTHONPATH=algo python -m story_video_agent.phase4a_optimize \
  --story-json "reports/story_t01/2022-11-28 克罗地亚vs加拿大.json" \
  --video-path "/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4" \
  --out-dir _local_render/phase4a_dry \
  --mode vlm-only \
  --targets equalizer_goal \
  --max-rounds 1 \
  --frames-per-round 2 \
  --frame-budget 4 \
  --max-api-calls 3 \
  --max-completion-tokens 256 \
  --real \
  --dry-check
```

检查输出：

- `targets` / `seed_windows`（应仅 equalizer ≈3065.903）
- `effective_caps.max_calls / max_cost_usd / max_completion_tokens`
- `official_video_rsi_models` vs `request_models`
- `vendor_compat` / `endpoint_ready`（密钥仅 `*_api_key_set` 布尔）
- `http_requests_sent: false`
- **不得**出现 API Key 明文

## 授权后真实运行（人工执行；本阶段不自动跑）

```bash
PYTHONPATH=algo python -m story_video_agent.phase4a_optimize \
  --story-json "reports/story_t01/2022-11-28 克罗地亚vs加拿大.json" \
  --video-path "/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4" \
  --plan-json reports/story_compose_phase3a1_croatia.json \
  --out-dir _local_render/phase4a_vlm_only \
  --mode vlm-only \
  --targets equalizer_goal \
  --max-rounds 1 \
  --frames-per-round 2 \
  --frame-budget 4 \
  --max-api-calls 3 \
  --max-completion-tokens 256 \
  --real \
  --v1-summary _local_render/phase3b/croatia_preview_summary.json
```

## 期望产物

- `phase4a_experiment_report.json`：原始/结构化 VLM、`frame_id`、`requested/actual_media_sec`、错误与 `http_attempts`
- preview 可选；**不得** `render_ready=true`
- go_ahead 仍 unresolved（本次未搜索）
- `final` 模式继续硬拒绝

## 禁止项

- 用 Mock / 伪造 `granted_by` / 模型 goal 标签绕过门禁
- `attest_semantic_result(passed)` 当作「已视觉核实进球」
- 未设 `STORY_INTERNAL_VERIFY_KEY` 时做生产成片授权
- 自动扩大 HTTP 次数绕过 `STORY_API_MAX_CALLS`
- 首次联调同时跑 `go_ahead_goal` 浪费额度
