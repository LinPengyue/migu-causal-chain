# Phase 4A.1：`--targets` 与首次 VLM-only 预检

**分支**: `story-va-phase2c` · **无付费 API** · **未跑 `--real` 实验**

## 变更

- CLI `--targets equalizer_goal|go_ahead_goal`（可多选；默认两者兼容）
- 首次真实联调固定：`--targets equalizer_goal` @ seed **3065.903s**；`max_rounds=1`、`frames_per_round=2`、`frame_budget=4`、HTTP≤3、`completion_tokens≤256`
- Video-RSI 官方双模型标签：Planner `deepseek-v4-pro`，VLM `qwen3.6-plus`（`request_model` = 服务商 ID）
- `--real --dry-check`：报告模型/端点/密钥是否配置、生效预算、兼容参数；**绝不发 HTTP**
- 费用字段始终声明为估算

## 预检产物

| 文件 | 说明 |
|------|------|
| `phase4a_vlm_only_drycheck.json` | mock dry-check（equalizer-only） |
| `phase4a_vlm_only_real_drycheck.json` | real 预检（本机缺门控 → ok=false，无 HTTP） |
| `phase4a_vlm_only_real_drycheck_ready.json` | 合成就绪环境预检（假 key，无 HTTP，密钥已脱敏） |
| `phase4a_vlm_only_playbook.md` | 人工联调步骤（不自动执行） |

## 回归

`PYTHONPATH=algo python -m unittest story_video_agent.test_phase4a_caps story_video_agent.test_phase4a`
