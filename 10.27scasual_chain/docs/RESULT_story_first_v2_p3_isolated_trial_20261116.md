# Story-First V2 P3：H5 零付费隔离实片试剪（2026-11-16）

基线：`a2e0b06f4d326ea51ce1abc92b2c5ff5c40eed64`  
产物目录：`/tmp/lpy1_story_first_v2_p3_isolated_trial_20261116/`  
付费：**0 HTTP**（未跑 Generator / Scorer / Planner / Vision）

**未修改正式 EDL**（仍 `b38434b9…`）；**未覆盖**既有 `story_clean.mp4`；**未自动接受**候选；试剪后停止。

## 1. 意图与临时 EDL

| 项 | 值 |
|----|----|
| intent | H5 `search_add` `story_first_ab22f01929b5cb4f59e6badd_01` |
| window | **[6395.81, 6418.07]** |
| insert | after `seg_buildup_event_000472` → before `seg_equalizer_goal_action` |
| evidence_status | `NO_ANNOTATED_REPLAY_OVERLAP` |
| first_live | `NOT_VERIFIED`（正式入版仍阻断） |
| apply | `applied_evidence_bound`；rejected=[] |

主线/进球/记分牌片段 media 未改；仅新增 `seg_story_first_ab22f01929b5cb4f59e6badd_01`。

## 2. 双版完整视频（可对照）

| 版本 | 路径 | 时长 |
|------|------|------|
| 原版 | `…/baseline/story_clean_original.mp4` | **94.877s** |
| 试剪 | `…/trial/story_clean_trial_h5.mp4` | **117.168s** |
| 试剪 QC | `…/trial/render/story_qc.mp4` | 117.168s |

Δ时长 **+22.291s** ≈ H5 窗 **22.26s**（差 0.031s，编码边界）。

成片时间轴（clean clips）：H5 位于 **40.61–62.90s**，紧接 equalizer **62.90s** 起。

## 3. QC

| 检查 | 结果 |
|------|------|
| 插入位置 | OK（buildup → H5 → equalizer） |
| 源 PTS 非递减 | OK |
| 片段 IoU≥0.2 重复 | 无 |
| AV | 双版均 h264 1280×720 + aac 44100/2ch |
| 正式 EDL/原片 | 未改 |

源时间缝：buildup→H5 **1677.36s**；H5→equalizer **18.854s**。

## 4. 验收焦点（故事铺垫，非质量结论）

静止帧（scoreboard）：buildup 末约 **47:05**；H5 **75:03–75:25**；equalizer 起始约 **75:44**；比分均 **UAE 0–1 OMA**。

- H5 **没有**填「落后记分牌 → 早期蓄力(event_000472)」空档（该空档仍在成片里以硬切跨越）。
- H5 填的是「早期蓄力镜头 → 扳平」之间的**晚段**空隙，并紧贴扳平前 ~19s。
- 窗内画面以中场争抢/交替球权为主（标注三次拦截；VLM：635 SUPPORTED，634/636 UNCERTAIN）。H5 末与 equalizer 起始之间仍隔 ~19s 源时间，且仍见对方持球推进——**不足以单独证明**已建立清晰的「进攻发起 → 扳平」因果链；更接近在扳平前插入一段落后背景下的中场拉锯，而非完整蓄力叙事弧。

## 5. 停止状态

- `candidate_accepted=false`
- `continue_revision=false`
- 正式入版仍待独立 FIRST_LIVE；本产物仅供人工对照审片。
