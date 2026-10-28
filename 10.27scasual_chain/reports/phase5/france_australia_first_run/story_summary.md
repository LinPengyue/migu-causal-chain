# 法国 逆转 澳大利亚

> 本稿为咪咕甲方可读的故事链内容摘要（候选审核）。非正式生产授权；画面语义尚未独立核验通过。

## 比赛与故事类型
- 对阵：法国 vs 澳大利亚
- 故事类型：逆风翻盘（T01）
- 故事主角：法国

## 故事标题
法国 逆转 澳大利亚

## 故事摘要
本场为「逆风翻盘」类型故事。对阵双方为法国与澳大利亚，系统认定的故事主角是法国（对手为澳大利亚）。比分确认轨迹为：0:0 → 0:1（澳大利亚取得进球后的比分确认） → 1:1（法国取得进球后的比分确认） → 2:1（法国取得进球后的比分确认） → 3:1（法国取得进球后的比分确认） → 4:1（法国取得进球后的比分确认）。上述时间为记分牌确认锚点，不等于进球动作发生时刻。叙事按铺垫、蓄力、转折、高潮、收尾组织：先交代造成（该弧内）落后的失球，再收录落后期间的相关进攻，随后是扳平与反超（及可能的扩大优势），最后以终场比分确认收束（远处「比赛结束」标注若不紧邻终场比分则不采用，以免误切其它转播）。当前结构化收录了 4 个判定为窗口完整的进球动作候选，另有 0 个进球动作因证据不足或花屏冲突降级为补证，摘要不将其表述为已核实进球。本文仅陈述算法已结构化的事实；未经验证的战术、球员动作与因果不作断言。

## 五段叙事过程
### 铺垫
- 标题卡（标题/说明卡）
- 落后比分确认：原片约 1534.7–1538.2 秒；比分确认（非进球动作）。

### 蓄力
- 蓄力阶段相关进攻/事件：原片约 1585.9–1597.9 秒；窗口完整候选。
- 蓄力阶段相关进攻/事件：原片约 2107.9–2119.9 秒；窗口完整候选。

### 转折
- 扳平进球动作：原片约 2398.1–2420.1 秒；进球动作候选·窗口完整。
- 扳平比分确认：原片约 2512.3–2515.8 秒；比分确认（非进球动作）。

### 高潮
- 反超进球动作：原片约 2714.2–2736.2 秒；进球动作候选·窗口完整。
- 反超比分确认：原片约 2903.3–2906.8 秒；比分确认（非进球动作）。
- 扩大优势进球动作：原片约 5422.7–5444.7 秒；进球动作候选·窗口完整。
- 扩大优势比分确认：原片约 5593.3–5596.8 秒；比分确认（非进球动作）。
- 扩大优势进球动作：原片约 5650.2–5672.2 秒；进球动作候选·窗口完整。
- 扩大优势比分确认：原片约 5819.5–5823.0 秒；比分确认（非进球动作）。

### 收尾
- 标题卡（标题/说明卡）

## 故事范围（全场背景 vs 本次剪辑弧）

本次剪辑主线是 T01「最后一次落后弧」；规划器可按需补充弧前背景摘要/关键比分牌，但不会默认剪成固定三事件，也不会强制纳入全部进球。整场轨迹见 full_match_score_path；弧前省略见 prior_score_turns_omitted；补入决策见 background_plan。

### 整场比分背景
- 0:0 @ 882.74s
- 0:1 @ 1535.65s（delta=right）
- 1:1 @ 2513.29s（delta=left）
- 2:1 @ 2904.31s（delta=left）
- 3:1 @ 5594.3s（delta=left）
- 4:1 @ 5820.46s（delta=left）

### 本次剪辑选取的最后翻盘弧
- 弧内落后起点：0:1 @ 1535.65s
- 扳平：1:1 @ 2513.29s
- 反超：2:1 @ 2904.31s

### 弧前省略的比分转折（未默认剪入）
- 0:0 @ 882.74s
- 规划器背景决策：mode=`none` · affects_understanding=`False` · reason=`no_meaningful_prior_score_changes`
- 不会固定为「落后→扳平→反超」三事件模板，也不会强制纳入全部进球。

## 关键比分变化（记分牌锚点）
- 比分确认 **0:0**（记分牌锚点约 882.74 秒；非进球动作时刻）
- 比分确认 **0:1**（记分牌锚点约 1535.65 秒；非进球动作时刻）
- 比分确认 **1:1**（记分牌锚点约 2513.29 秒；非进球动作时刻）
- 比分确认 **2:1**（记分牌锚点约 2904.31 秒；非进球动作时刻）
- 比分确认 **3:1**（记分牌锚点约 5594.3 秒；非进球动作时刻）
- 比分确认 **4:1**（记分牌锚点约 5820.46 秒；非进球动作时刻）

## 事件关系说明
- 叙事承接：各段按故事顺序衔接，**不代表**已证实战术因果。
- 时间先后：有时间戳的镜头按原片时间排序。
- 比分状态：score_path 相邻节点表示记分牌确认的比分变化。
- 事件关联：进球镜头与事件表/因果链 live 进球的规则匹配；**不等于**独立语义核验通过，也**不等于**已证实攻防因果。

## 镜头来源与核验状态（概要）
- 业务版与内部 QC 版共用同一剪辑时间轴（同一 EDL）。
- 全部镜头为算法候选：`render_ready=false`，未授予正式成片。
- 进球动作优先绑定事件表/因果链中的 live 进球时间；比分牌仅作确认，不替代进球。
- 完整进球动作候选 4 个；不完整/补证 0 个。

## 不能确认的关键事实与缺失证据
- 缺失证据标记：missing_live_goal_action:opponent_opening
- 缺失证据标记：behind_carrier_unresolved:event_000027
- 缺失证据标记：equalizer_carrier_unresolved:event_000082
- 缺失证据标记：go_ahead_carrier_unresolved:event_000091
- 缺失证据标记：lead_extend_1_carrier_unresolved:event_000260
- 缺失证据标记：lead_extend_2_carrier_unresolved:event_000264
- 缺失证据标记：ending_wrap_score_skipped_duplicate_of_go_ahead_board
- 缺失证据标记：ending_match_end_rejected:match_end_beyond_candidate_horizon:dt=1421.34

---

## 技术附录

以下字段供研发/算法复审，不作为甲方主读内容。完整图见 `story_graph.json`，剪辑表见 `candidate_edl.json`，方案见 `story_plan.json`。

- match_id: `2022年11月23日 法国vs澳大利亚`
- story_tier: `story`
- protagonist_side: `left`
- blocking_reasons: `['equalizer_goal_action_not_render_ready', 'go_ahead_goal_action_not_render_ready', 'missing_opponent_opening_goal_action']`

| 段 | 叙事位 | 角色 | 原片入点 | 原片出点 | 关联事件 | 时间状态 | 进球完整 | 核验 |
|---|---|---|---|---|---|---|---|---|
| seg_title_open | 铺垫 | story_title | None | None | [] | placeholder_title | None | candidate_only / semantic_unverified |
| seg_setup_deficit | 铺垫 | deficit_scoreboard_anchor | 1534.65 | 1538.15 | [] | score_path_only | None | candidate_only / semantic_unverified |
| seg_buildup_event_000031 | 蓄力 | buildup_action | 1585.9 | 1597.9 | ['event_000031'] | event_ms | None | candidate_only / semantic_unverified |
| seg_buildup_event_000072 | 蓄力 | buildup_action | 2107.89 | 2119.89 | ['event_000072'] | event_ms | None | candidate_only / semantic_unverified |
| seg_equalizer_goal_action | 转折 | equalizer_goal_action | 2398.091 | 2420.091 | ['causal:ann_0004:event_000020'] | linked_event_ms | True | candidate_only / semantic_unverified |
| seg_equalizer_scoreboard | 转折 | equalizer_scoreboard_anchor | 2512.29 | 2515.79 | [] | score_path_only | None | candidate_only / semantic_unverified |
| seg_go_ahead_goal_action | 高潮 | go_ahead_goal_action | 2714.188 | 2736.188 | ['causal:ann_0007:event_000037'] | linked_event_ms | True | candidate_only / semantic_unverified |
| seg_go_ahead_scoreboard | 高潮 | go_ahead_scoreboard_anchor | 2903.31 | 2906.81 | [] | score_path_only | None | candidate_only / semantic_unverified |
| seg_lead_extend_1_goal_action | 高潮 | lead_extend_1_goal_action | 5422.743 | 5444.743 | ['causal:ann_0011:event_000054'] | linked_event_ms | True | candidate_only / semantic_unverified |
| seg_lead_extend_1_scoreboard | 高潮 | lead_extend_1_scoreboard_anchor | 5593.3 | 5596.8 | [] | score_path_only | None | candidate_only / semantic_unverified |
| seg_lead_extend_2_goal_action | 高潮 | lead_extend_2_goal_action | 5650.164 | 5672.164 | ['causal:ann_0014:event_000067'] | linked_event_ms | True | candidate_only / semantic_unverified |
| seg_lead_extend_2_scoreboard | 高潮 | lead_extend_2_scoreboard_anchor | 5819.46 | 5822.96 | [] | score_path_only | None | candidate_only / semantic_unverified |
| seg_title_close | 收尾 | story_wrap_title | None | None | [] | placeholder_title | None | candidate_only / semantic_unverified |
