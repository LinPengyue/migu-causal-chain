# Story Video Agent Phase 2C

## Verdict
Trusted visual feedback + remote API 联调就绪（默认 mock）。生产/`require_real` 缺密钥硬失败；degraded/非法 JSON/无效 frame_id 不得 observed。

## Trajectory (mock France focus: 扳平 / 反超 / 庆祝)
- Status: `observed` · Schema: `story-video-agent-plan-2c` · Algorithm: `None`
- Steps: 11 · Planner modes: `['rule', 'rule', 'rule', 'rule', 'rule', 'rule', 'rule', 'rule', 'rule', 'rule', 'rule']`
- Tasks: [('verify_equalizer_goal_action', 'observed'), ('verify_go_ahead_goal_action', 'observed'), ('post_climax_reaction', 'observed')]

Full step log: `reports/story_video_agent_phase2c_report.json` → `trajectory_planner_tools_vlm_memory`.

## Raw vs normalized evidence
See `raw_vs_normalized_evidence` in the JSON report (mock cites first input frame only).

## Failure / degradation
illegal_empty_json, invalid_frame_id, degraded_mode, vlm_score_conflict, retryable_429, non_retryable_401, search_budget_exhausted

## Token / cost (mock — real_requests=0)
```json
{
  "mode": "mock",
  "api_enabled": false,
  "require_real": false,
  "force_mock": true,
  "planner": {
    "role": "planner",
    "base_url": "",
    "model": "",
    "timeout_sec": 60.0,
    "max_retries": 2,
    "rpm": 30.0,
    "api_key_set": false
  },
  "vision": {
    "role": "vision",
    "base_url": "",
    "model": "",
    "timeout_sec": 60.0,
    "max_retries": 2,
    "rpm": 30.0,
    "api_key_set": false
  },
  "planner_ready": false,
  "vision_ready": false,
  "max_calls": null,
  "max_cost_usd": null,
  "notes": "Story Video Agent remote API (Phase 2C):\n  STORY_API_ENABLE=1                    require real HTTP (missing config => hard fail)\n  STORY_LLM_BASE_URL / OPENAI_BASE_URL\n  STORY_LLM_API_KEY  / OPENAI_API_KEY\n  STORY_LLM_MODEL\n  STORY_VLM_BASE_URL / STORY_VLM_API_KEY / STORY_VLM_MODEL\n  STORY_LLM_TIMEOUT_SEC / STORY_LLM_MAX_RETRIES / STORY_LLM_RPM\n  STORY_API_SMOKE=1                     explicit billed smoke entry only\n  STORY_API_MAX_CALLS / STORY_API_MAX_COST_USD  hard caps for smoke/real runs\n\nprovider modes: mock | real | degraded\nLogs never print API keys or image base64.",
  "usage": {
    "calls": 3,
    "real_requests": 0,
    "cached_hits": 0,
    "mock_calls": 3,
    "degraded_calls": 0,
    "ok": 3,
    "failures": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "cached_tokens_reported": 0,
    "est_cost_usd_real": 0,
    "est_cost_usd_cached_replay": 0,
    "elapsed_sec_real": 0,
    "by_role": {
      "vision": {
        "real_requests": 0,
        "tokens": 0,
        "est_cost_usd": 0
      }
    },
    "records": [
      {
        "role": "vision",
        "model": "mock",
        "ok": true,
        "mode": "mock",
        "elapsed_sec": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "est_cost_usd": 0.0,
        "cached": false,
        "error": "",
        "http_status": 0,
        "retryable": false
      },
      {
        "role": "vision",
        "model": "mock",
        "ok": true,
        "mode": "mock",
        "elapsed_sec": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "est_cost_usd": 0.0,
        "cached": false,
        "error": "",
        "http_status": 0,
        "retryable": false
      },
      {
        "role": "vision",
        "model": "mock",
        "ok": true,
        "mode": "mock",
        "elapsed_sec": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "est_cost_usd": 0.0,
        "cached": false,
        "error": "",
        "http_status": 0,
        "retryable": false
      }
    ]
  }
}
```

## Real API smoke（显式开启，默认不跑）
```bash
STORY_API_ENABLE=1 STORY_API_SMOKE=1 \
STORY_LLM_BASE_URL=... STORY_LLM_API_KEY=... STORY_LLM_MODEL=... STORY_VLM_MODEL=... \
STORY_API_MAX_CALLS=3 STORY_API_MAX_COST_USD=0.05 \
python -m story_video_agent.smoke_api \
  --story-json <t01.json> \
  --video-path "/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4" \
  --croatia-setup-focus
```
无法国比赛实片；合成视频 mock 描述不得当作识别准确率。

## Regression
37 OK (1 skipped billed smoke).
