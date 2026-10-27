# Story Video Agent Phase 2C.1 — 真实 API 联调准备

## Verdict
联调入口拆成 **`vlm-only`** / **`planner-vlm-loop`**；HTTP 成功/失败/重试均计入 `STORY_API_MAX_CALLS`；缓存命中单独统计；单次 `STORY_API_MAX_COMPLETION_TOKENS`；费用字段标明为**估算**（非账单硬上限）。默认不跑计费请求。

## Branch vs main
- Tip: `story-va-phase2c`（含 2C + 2C.1）
- Merge-base with `origin/main`: Phase 2B (`0fb8fa3`)
- **未** force-push / 覆盖 `main`

## Smoke modes（显式开启才执行 HTTP）
```bash
STORY_API_ENABLE=1 STORY_API_SMOKE=1 \
STORY_LLM_BASE_URL=... STORY_LLM_API_KEY=... STORY_LLM_MODEL=... \
STORY_VLM_MODEL=... \
STORY_API_MAX_CALLS=3 STORY_API_MAX_COST_USD=0.05 \
STORY_API_MAX_COMPLETION_TOKENS=512 \
python -m story_video_agent.smoke_api --mode vlm-only \
  --story-json "reports/story_t01/2022-11-28 克罗地亚vs加拿大.json" \
  --video-path "/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4" \
  --gap-id missing_setup_visual --out reports/smoke_vlm_only.json

# 预检（无 HTTP）：加 --dry-check
# Planner 反馈：--mode planner-vlm-loop
```

### 报告字段
| 区块 | 内容 |
|------|------|
| `vlm` | frame_ids、视觉描述、raw excerpt、usage、est_cost |
| `planner` | decision、interprets_as（stop / refine:* / continue_search） |
| 调用 | `http_attempts`、`cached_hits`、`elapsed_sec`、`est_cost_usd_real` |
| 声明 | `cost_disclaimer` |

### 禁止
- mock 结果冒充 real 成功（`_assert_real_not_mock`）
- 无 `STORY_API_SMOKE` / `STORY_API_ENABLE` / 端点·密钥·视频·费用 soft-cap 时开跑

## Auditable failure_status
`empty_json` · `illegal_json` · `invalid_frame_id` · `unrelated_visual` · `timeout` · `http_429` · `http_5xx` · `budget_exhausted` · `cost_estimate_cap` · `degraded`

## Regression（无计费）
`PYTHONPATH=. python3 -m unittest story_video_agent.test_dry_run story_video_agent.test_media story_video_agent.test_perception story_video_agent.test_phase2c story_video_agent.test_phase2c1 -v`  
→ **48 OK**（1 skipped billed smoke）

本提交**未**执行付费联调；克罗地亚实片路径已预留，由用户显式开启。
