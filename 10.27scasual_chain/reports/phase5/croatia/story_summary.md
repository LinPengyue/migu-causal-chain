# 克罗地亚 逆转 加拿大

> 本稿为咪咕甲方可读的故事链内容摘要（候选审核）。非正式生产授权；画面语义尚未独立核验通过。

## 比赛与故事类型
- 对阵：克罗地亚 vs 加拿大
- 故事类型：逆风翻盘（T01）
- 故事主角：克罗地亚

## 故事标题
克罗地亚 逆转 加拿大

## 故事摘要
本场为「逆风翻盘」类型故事。对阵双方为克罗地亚与加拿大，系统认定的故事主角是克罗地亚（对手为加拿大）。本摘要与成片主线是克罗地亚在「最后一次落后弧」上的失球→扳平→反超（T01 选定弧），不得等同于全场所有比分故事。比分确认轨迹为：0:1 → 1:1（克罗地亚取得进球后的比分确认） → 2:1（克罗地亚取得进球后的比分确认） → 3:1（克罗地亚取得进球后的比分确认） → 4:1（克罗地亚取得进球后的比分确认）。上述时间为记分牌确认锚点，不等于进球动作发生时刻。叙事按铺垫、蓄力、转折、高潮、收尾组织：先交代造成（该弧内）落后的失球，再收录落后期间的相关进攻，随后是扳平与反超（及可能的扩大优势），最后以终场比分确认收束（远处「比赛结束」标注若不紧邻终场比分则不采用，以免误切其它转播）。当前结构化收录了 5 个判定为窗口完整的进球动作候选，另有 0 个进球动作因证据不足或花屏冲突降级为补证，摘要不将其表述为已核实进球。本文仅陈述算法已结构化的事实；未经验证的战术、球员动作与因果不作断言。

## 五段叙事过程
### 铺垫
- 标题卡（标题/说明卡）
- 对手造成落后的进球动作：原片约 968.1–990.1 秒；进球动作候选·窗口完整。
- 落后比分确认：原片约 1078.1–1081.6 秒；比分确认（非进球动作）。

### 蓄力
- 蓄力阶段相关进攻/事件：原片约 1153.3–1165.3 秒；窗口完整候选。
- 蓄力阶段相关进攻/事件：原片约 2200.2–2212.2 秒；窗口完整候选。

### 转折
- 扳平进球动作：原片约 3053.9–3075.9 秒；进球动作候选·窗口完整。
- 扳平比分确认：原片约 3145.0–3148.5 秒；比分确认（非进球动作）。

### 高潮
- 反超进球动作：原片约 3511.6–3533.6 秒；进球动作候选·窗口完整。
- 反超比分确认：原片约 3696.3–3699.8 秒；比分确认（非进球动作）。
- 扩大优势进球动作：原片约 6305.2–6315.8 秒；进球动作候选·窗口完整。
- 扩大优势进球动作：原片约 6316.7–6327.2 秒；进球动作候选·窗口完整。
- 扩大优势比分确认：原片约 6407.7–6411.2 秒；比分确认（非进球动作）。

### 收尾
- 终场/收尾画面：原片约 7857.4–7862.4 秒；窗口完整候选。
- 标题卡（标题/说明卡）

## 故事范围（全场背景 vs 本次剪辑弧）

本次剪辑主线是 T01「最后一次落后弧」上的扳平/反超（及弧内失球），不是默认收录全场每一次比分转折。整场比分背景见 full_match_score_path；弧前省略的转折见 prior_score_turns_omitted。

### 整场比分背景
- 0:1 @ 1079.06s
- 1:1 @ 3145.98s（delta=left）
- 2:1 @ 3697.35s（delta=left）
- 3:1 @ 6408.7s（delta=left）
- 4:1 @ 7858.37s（delta=left）

### 本次剪辑选取的最后翻盘弧
- 弧内落后起点：0:1 @ 1079.06s
- 扳平：1:1 @ 3145.98s
- 反超：2:1 @ 3697.35s

## 关键比分变化（记分牌锚点）
- 比分确认 **0:1**（记分牌锚点约 1079.06 秒；非进球动作时刻）
- 比分确认 **1:1**（记分牌锚点约 3145.98 秒；非进球动作时刻）
- 比分确认 **2:1**（记分牌锚点约 3697.35 秒；非进球动作时刻）
- 比分确认 **3:1**（记分牌锚点约 6408.7 秒；非进球动作时刻）
- 比分确认 **4:1**（记分牌锚点约 7858.37 秒；非进球动作时刻）

## 事件关系说明
- 叙事承接：各段按故事顺序衔接，**不代表**已证实战术因果。
- 时间先后：有时间戳的镜头按原片时间排序。
- 比分状态：score_path 相邻节点表示记分牌确认的比分变化。
- 事件关联：进球镜头与事件表/因果链 live 进球的规则匹配；**不等于**独立语义核验通过，也**不等于**已证实攻防因果。

## 镜头来源与核验状态（概要）
- 业务版与内部 QC 版共用同一剪辑时间轴（同一 EDL）。
- 全部镜头为算法候选：`render_ready=false`，未授予正式成片。
- 进球动作优先绑定事件表/因果链中的 live 进球时间；比分牌仅作确认，不替代进球。
- 完整进球动作候选 5 个；不完整/补证 0 个。

## 不能确认的关键事实与缺失证据
- 缺失证据标记：equalizer_carrier_unresolved:event_000068
- 缺失证据标记：go_ahead_carrier_unresolved:event_000076
- 缺失证据标记：lead_extend_1_carrier_unresolved:event_000118
- 缺失证据标记：lead_extend_2_carrier_unresolved:event_000155
- 缺失证据标记：missing_live_goal_action:lead_extend_2
- 缺失证据标记：ending_full_time_needs_visual_verify

---

## 技术附录

以下字段供研发/算法复审，不作为甲方主读内容。完整图见 `story_graph.json`，剪辑表见 `candidate_edl.json`，方案见 `story_plan.json`。

- match_id: `2022-11-28 克罗地亚vs加拿大`
- story_tier: `story`
- protagonist_side: `left`
- blocking_reasons: `['equalizer_goal_action_not_render_ready', 'go_ahead_goal_action_not_render_ready', 'missing_trusted_goal_action:lead_extend_2']`

| 段 | 叙事位 | 角色 | 原片入点 | 原片出点 | 关联事件 | 时间状态 | 进球完整 | 核验 |
|---|---|---|---|---|---|---|---|---|
| seg_title_open | 铺垫 | story_title | None | None | [] | placeholder_title | None | candidate_only / semantic_unverified |
| seg_opponent_opening_goal_action | 铺垫 | opponent_opening_goal_action | 968.137 | 990.137 | ['event_000004'] | linked_event_ms | True | candidate_only / semantic_unverified |
| seg_setup_deficit | 铺垫 | deficit_scoreboard_anchor | 1078.06 | 1081.56 | ['event_000004'] | score_path_only | None | candidate_only / semantic_unverified |
| seg_buildup_event_000007 | 蓄力 | buildup_action | 1153.3 | 1165.3 | ['event_000007'] | event_ms | None | candidate_only / semantic_unverified |
| seg_buildup_event_000040 | 蓄力 | buildup_action | 2200.2 | 2212.2 | ['event_000040'] | event_ms | None | candidate_only / semantic_unverified |
| seg_equalizer_goal_action | 转折 | equalizer_goal_action | 3053.903 | 3075.903 | ['event_000021'] | linked_event_ms | True | candidate_only / semantic_unverified |
| seg_equalizer_scoreboard | 转折 | equalizer_scoreboard_anchor | 3144.98 | 3148.48 | [] | score_path_only | None | candidate_only / semantic_unverified |
| seg_go_ahead_goal_action | 高潮 | go_ahead_goal_action | 3511.574 | 3533.574 | ['event_000022'] | linked_event_ms | True | candidate_only / semantic_unverified |
| seg_go_ahead_scoreboard | 高潮 | go_ahead_scoreboard_anchor | 3696.35 | 3699.85 | [] | score_path_only | None | candidate_only / semantic_unverified |
| seg_lead_extend_1_goal_action_approach | 高潮 | lead_extend_1_goal_action_approach | 6305.199 | 6315.8 | ['event_000025'] | linked_event_ms | True | candidate_only / semantic_unverified |
| seg_lead_extend_1_goal_action | 高潮 | lead_extend_1_goal_action | 6316.7 | 6327.199 | ['event_000025'] | linked_event_ms | True | candidate_only / semantic_unverified |
| seg_lead_extend_1_scoreboard | 高潮 | lead_extend_1_scoreboard_anchor | 6407.7 | 6411.2 | [] | score_path_only | None | candidate_only / semantic_unverified |
| seg_ending_story_wrap_score | 收尾 | ending_story_wrap_score | 7857.37 | 7862.37 | ['event_000155'] | score_path_only | None | candidate_only / semantic_unverified |
| seg_title_close | 收尾 | story_wrap_title | None | None | [] | placeholder_title | None | candidate_only / semantic_unverified |
