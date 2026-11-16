# Story-First V2 P3：H5 成片评价（零付费结构性 + 付费预检）

基线：`b98d22d840ef512396d14736c09d29ed92afe188`  
产物：`/tmp/lpy1_story_first_v2_p3_eval_offline_20261116/`  
付费：**0 HTTP**（未擅自调用 VLM）

复用现有模块，**未新建**重复评价器：
`global_story_critic.structural_diagnosis` · `story_video_verifier.verify_story_revision` ·
`dual_video_vision_verifier.extract_aligned_dual_frames` · `story_revision_planner.plan_from_diagnosis` ·
`self_revise_agent.decide_accept`

双版视频仅复用、未覆盖；正式 EDL 未改（`b38434b9…`）。未重跑 Generator / Scorer / Planner 候选 / P2 事件核验。

## 1. 双版结构性比较（Critic）

| | Baseline | Trial(H5) |
|--|----------|-----------|
| issues | 3 | 3 |
| 大源跳切 | buildup→equalizer **1718.5s** | buildup→H5 **1677.4s**（跳切**未消除**，仅改挂点） |
| H5→equalizer | — | 源间隔 **18.85s**（结构上更贴扳平） |
| 进球/主线 | 完整 | **完整未改** |

结构结论：H5 **不能**从结构上证明补上了「落后→蓄力」叙事；大跳切仍在 early buildup 之后。大跳切均为 `info` + `needs_video_verify`，**禁止**当成已确认缺桥缺陷或已证明因果。

## 2. Verifier（离线规则轨）

`verify_story_revision(..., vision_backed=False, verdict_provenance=OFFLINE_RULE)`：

| 项 | 结果 |
|----|------|
| semantic | **NOT_EVALUATED** |
| safety | UNKNOWN |
| quality | UNCERTAIN |
| issue_effect | UNOBSERVED |
| candidate_accepted | **false** |
| text-only ACCEPT | 禁止（`text_only_verifier_forbidden`） |

无视觉引用时，**不能**判定 H5 有正向叙事价值。

## 3. Revision Planner / 自主决策

| 层 | 输出 | 含义 |
|----|------|------|
| `plan_from_diagnosis`(trial/baseline) | **UNRESOLVED** | 跳切假设需看片；禁止仅因大 gap 自动 search_add |
| `decide_accept`(loop) | accept=false | verifier 未评估 → 拒绝写入 best |
| **候选处置（本轮自主）** | **REJECT** | 不保留 H5 入正式/best；非 REVISE（无已确认可改缺陷驱动） |

理由（模型输入**不含**人工认可）：
1. 无 dual-vision 语义通过 → 不能主张正向叙事价值  
2. `story_first_preview_only` + `FIRST_LIVE=NOT_VERIFIED`  
3. 结构上大跳切仍在；未证明连贯蓄力弧  

`KEEP` 会在付费 dual-vision 给出带帧引用的 `improved` 且通过门禁后才可能成立；本轮未调用。

## 4. 付费调用预检（未执行）

真实成片叙事价值评价需要：

| 项 | 预估 |
|----|------|
| 模块 | `run_dual_video_vision_verifier` |
| HTTP | **1** |
| 帧 | **8**（已本地抽好：pre_edit / edit_impact / post_edit / global_ending ×2） |
| model | Qwen3.7-Plus（同 Vision1） |
| prompt/completion | ~23891 / ~800 |
| est_cost | **~$0.0039** |

预检帧已就绪：`dual_preflight/`。**等待单独授权后才可调用。**

## 5. 验收焦点

| 问题 | 本轮答案 |
|------|----------|
| Agent 能否独立判定 H5 有正向叙事价值？ | **否**（正确拒判） |
| 该判定是否有可核验视频依据？ | 结构/EDL/时长可核验；**语义正向价值尚无可引用成片帧的 VLM 证据** |
| 下一步最小动作 | 授权 1× dual-video Vision → 再跑 Verifier+decide_accept；仍不改正式 EDL 直至通过 |
