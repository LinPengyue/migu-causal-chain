# V3-A Real API Adapter Fix Evaluation

**分支：** `story-va-v3-a`  
**对照联调：** France `v3a_self_revise_fr_real_20261104_r1`（报告 `d52df8c`）  
**本轮付费 API（适配修复阶段）：** **否**  
**V3-R 冻结：** 未改  
**实验阈值 75：** 未改  
**新的严格门禁：** 无

## 修复摘要

### P0 Planner 归一化（`validate_planner_output`）

| 项 | 处理 |
|----|------|
| `tool` / `tool_name` | 统一读取 |
| 工具别名 | `observe_goal_action_window` / `verify_segment_visual_truth` / `review_segment_scope` → `vlm_observe` |
| 相对窗 | `{start,end}_offset_sec` + 可信 `anchor_id` → 绝对媒体秒；越界拒绝 |
| 绝对窗 | 须落在 anchor lookback/after 包络；禁止自由 PTS |
| intents | `target`/`role` 映射到 `opponent_opening_goal_action` + `score_node:behind_start` 等 |
| 丢弃审计 | 每条含 `raw` / `reason` / `suggested_fix` |
| 静默丢弃 | 可恢复 tool 全部变 0 → `planner_normalization_silent_drop`（拒绝伪成功） |

**离线重放真实 `planner_result.json`：** ≥3 条 tool 保留；opening 相对窗落到 ≈1345.65；`search_add` 获得 role+anchor。

### P0 Verifier 空正文

| 项 | 处理 |
|----|------|
| 状态拆分 | `http_ok` / `generation_ok` / `structured_ok` |
| 空正文 | `EMPTY_MODEL_CONTENT`（不再误报 empty VLM response） |
| Provider | `verify_decision()`：endpoint=planner，`stats_role=verifier`；仅在已支持 video_rsi / 显式 env 时发 `thinking={type:disabled}` |
| 提示词 | 短 JSON、禁止 coverage 进 hard_vetoes |
| 费用分账 | `by_role.verifier` 与 `planner` / `vision` 分开 |

### P1 宽松 Verifier

`missing_required_node` 等 coverage veto **降级为 issues**（覆盖率修订信号）；保留 replay / 比分球队 / 损坏 / 编造时间 hard veto。

## 测试

```text
76 / 76 OK  (test_v3a_*.py，含 test_v3a_real_api_adapter_fix)
```

## 真实复测（适配修复后，`max_rounds=1`）

**目录：** `…/v3a_self_revise_fr_real_20261104_r2_adapter/`  
**代码 SHA：** `ad760e3`

| 项 | 结果 |
|----|------|
| 完整执行 | 是；Planner+VLM×3+Verifier 均 **real**；费用分账 planner/vision/verifier 分开 |
| 费用 | ≈ **$0.0133**（http 5 ok / 0 fail） |
| EDL | 工作副本新增 `opponent_opening_goal_action` `[1385.65,1415.65]`；`first_live=NOT_VERIFIED`；冻结 V3-R **未改** |
| `decide_accept(loop)` | `p0_repair` 保留候选 |
| `decide_release` | **拒绝**（`release_blocked_pending_goal_segments`） |
| 候选 MP4 | `v3a_candidate_render/story_clean.mp4`（≈41MB）、`story_qc.mp4`（≈46MB）；时长 ≈142s |
| 成片质量宣称 | **否** — 仅为候选预览；opening 未核验为首次 LIVE；`render_ready=false` |

## 下一步

人工抽查 `[1385.65,1415.65]` 是否确为 opening LIVE；未核验前不得当作正式改善。
