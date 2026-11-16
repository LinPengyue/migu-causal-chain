# Story-First V2：`75f31c6` 拉取 + H5 离线 P3 就绪复核（2026-11-16）

代码：`75f31c64aca0da5933b5adc130f67e9890d5efae`  
前置 Vision 报告：`57119fe`（1× Qwen3.7-Plus，本轮**未**重呼）  
产物：`/tmp/lpy1_story_first_v2_p3_ready_offline_20261116/`  
付费：**0 HTTP**

未重跑 Generator / Causal Scorer / Planner；未改正式 EDL；**未渲染** P3 实片。

## 1. 策略对齐（本 commit）

1. 人工原子标注为事件事实依据；VLM `UNCERTAIN` 在标注对齐时可进 `advisory`，明确视觉反证仍阻断。
2. 隔离试剪按标注回放/慢动作做重叠检查；通过记 `NO_ANNOTATED_REPLAY_OVERLAP`。独立 `FIRST_LIVE` 仍管正式入版。

## 2. 回归

| 范围 | 结果 |
|------|------|
| `test_v3a_story_first_closed_loop` + continuous_broadcast | 33 passed |
| `-k 'story_first or continuous_broadcast or first_live_window'` | **82 passed** / 632 deselected |

未重跑 V3-A 全量（用户侧基线：637 passed / 14 failed / 66 skipped）。

## 3. H5 离线门禁（复用 Vision1 观测 + 交付标注）

| 项 | 值 |
|----|----|
| events | `…/01_enrich/events_enriched.json` `33958b10…` |
| teams | team_1 阿联酋/白 · team_2 阿曼/红 |
| annotated_ids | 634 / 635 / 636 |
| replay overlap | **NO_ANNOTATED_REPLAY_OVERLAP** |
| Vision 复用 | 634 UNCERTAIN · 635 SUPPORTED · 636 UNCERTAIN |
| advisory（保留） | 634、636 UNCERTAIN |
| blocking feedback | [] |
| status | **READY_FOR_TRIAL** |
| intent | `search_add` `[6395.81, 6418.07]` |
| `story_first_preview_only` | **true** |
| FIRST_LIVE | NOT_VERIFIED（正式入版仍阻断） |

## 4. 结论

- P2 离线验收通过；H5 **具备进入 P3 隔离实片试剪**条件。
- 试剪产物仅供成片核验/人工审片；**不得**因本意图写入正式 EDL。
- 下一步需**单独授权** P3 渲染（仍 0 算法重跑）；FIRST_LIVE 认证仍是正式入版前置。
