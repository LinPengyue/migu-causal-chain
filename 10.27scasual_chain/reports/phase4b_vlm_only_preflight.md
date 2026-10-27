# Phase 4B 首次真实 VLM-only — 预检报告（无计费）

**分支**: `story-va-phase2c` @ `26f5e9e`  
**状态**: **预检通过** · **尚未执行 `--real` HTTP** · 等待明确授权

## 你上次失败原因

只开了 `STORY_API_ENABLE / PHASE4A_REAL / SMOKE` 与 caps，**未 `source` 本地密钥文件**，故 `BASE_URL / MODEL / API_KEY` 全空。

正确加载：

```bash
cd /tmp/migu-va2c/10.27scasual_chain
set -a; source _local_render/phase4a_paratera.env; set +a
export STORY_API_ENABLE=1 STORY_PHASE4A_REAL=1 STORY_API_SMOKE=1
```

## 环境检查

| 项 | 结果 |
|----|------|
| Git | `story-va-phase2c` / `26f5e9e` |
| 视频 | `/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4` 存在 |
| Story JSON | `reports/story_t01/2022-11-28 克罗地亚vs加拿大.json` 存在 |
| Plan JSON | `reports/story_compose_phase3a1_croatia.json` 存在 |
| Base URL | `https://llmapi.paratera.com/v1` |
| request_model Planner | `DeepSeek-V4-Pro-0813`（vlm-only **不调用**） |
| request_model VLM | `Qwen3.6-Plus` |
| 官方标签 | planner=`deepseek-v4-pro` / vision=`qwen3.6-plus` |
| API Key | 已设置（仅布尔；未写入报告明文） |

## Dry-check（`--real --dry-check`）

- `ok=true` · `http_requests_sent=false` · `billing_allowed=true`
- `endpoint_ready.roles_ready=true`（仅 vision）
- caps: `max_calls=3` · `max_cost_usd=0.10`（估算）· `max_completion_tokens=256`
- targets: 仅 `equalizer_goal` · seed **3065.903** · window **3059.903–3071.903**
- 产物: `reports/phase4b_vlm_only_preflight.json` · `reports/phase4b_vlm_only_preflight_summary.json`

## 授权后将执行（尚未跑）

```bash
PYTHONPATH=algo python -m story_video_agent.phase4a_optimize \
  --story-json "reports/story_t01/2022-11-28 克罗地亚vs加拿大.json" \
  --video-path "/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4" \
  --plan-json reports/story_compose_phase3a1_croatia.json \
  --out-dir _local_render/phase4a_real_vlm1 \
  --mode vlm-only --targets equalizer_goal \
  --max-rounds 1 --frames-per-round 2 --frame-budget 4 \
  --max-api-calls 3 --max-completion-tokens 256 \
  --real \
  --v1-summary _local_render/phase3b/croatia_preview_summary.json
```

门禁保持：go_ahead unresolved · `render_ready=false` · `final` 硬拒绝 · 观察不作成片授权。
