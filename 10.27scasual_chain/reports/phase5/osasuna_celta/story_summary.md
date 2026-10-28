# 塞尔塔维戈 逆转 奥萨苏纳

> 本稿为咪咕甲方可读的故事链内容摘要（候选审核）。非正式生产授权；画面语义尚未独立核验通过。

## 比赛与故事类型
- 对阵：奥萨苏纳 vs 塞尔塔维戈
- 故事类型：逆风翻盘（T01）
- 故事主角：塞尔塔维戈

## 故事标题
塞尔塔维戈 逆转 奥萨苏纳

## 故事摘要
本场为「逆风翻盘」类型故事。对阵双方为奥萨苏纳与塞尔塔维戈，系统认定的故事主角是塞尔塔维戈（对手为奥萨苏纳）。本摘要主线是塞尔塔维戈在「最后一次落后」之后完成的扳平与反超（T01 最后一次落后弧），并不默认展开赛前所有历史进球过程。比分确认轨迹为：0:0 → 0:1（塞尔塔维戈取得进球后的比分确认） → 1:1（奥萨苏纳取得进球后的比分确认） → 2:1（奥萨苏纳取得进球后的比分确认） → 2:2（塞尔塔维戈取得进球后的比分确认） → 2:3（塞尔塔维戈取得进球后的比分确认）。上述时间为记分牌确认锚点，不等于进球动作发生时刻。叙事按铺垫、蓄力、转折、高潮、收尾组织：先交代造成（该弧内）落后的失球，再收录落后期间的相关进攻，随后是扳平与反超（及可能的扩大优势），最后以终场比分确认收束（远处「比赛结束」标注若不紧邻终场比分则不采用，以免误切其它转播）。当前结构化收录了 3 个判定为窗口完整的进球动作候选，另有 0 个进球动作因证据不足或花屏冲突降级为补证，摘要不将其表述为已核实进球。本文仅陈述算法已结构化的事实；未经验证的战术、球员动作与因果不作断言。

## 五段叙事过程
### 铺垫
- 标题卡（标题/说明卡）
- 对手造成落后的进球动作：原片约 3122.0–3144.0 秒；进球动作候选·窗口完整。
- 落后比分确认：原片约 3198.7–3202.2 秒；比分确认（非进球动作）。

### 蓄力
- 蓄力阶段相关进攻/事件：原片约 3204.8–3216.8 秒；窗口完整候选。
- 蓄力阶段相关进攻/事件：原片约 5581.6–5593.6 秒；窗口完整候选。

### 转折
- 扳平进球动作：原片约 5645.6–5667.6 秒；进球动作候选·窗口完整。
- 扳平比分确认：原片约 5711.0–5714.5 秒；比分确认（非进球动作）。

### 高潮
- 反超进球动作：原片约 6779.9–6801.9 秒；进球动作候选·窗口完整。

### 收尾
- 终场/收尾画面：原片约 6880.9–6884.4 秒；比分确认（非进球动作）。
- 标题卡（标题/说明卡）

## 关键比分变化
- 比分确认 **0:0**（记分牌锚点约 425.71 秒；非进球动作时刻）
- 比分确认 **0:1**（记分牌锚点约 2071.43 秒；非进球动作时刻）
- 比分确认 **1:1**（记分牌锚点约 2660.82 秒；非进球动作时刻）
- 比分确认 **2:1**（记分牌锚点约 3199.66 秒；非进球动作时刻）
- 比分确认 **2:2**（记分牌锚点约 5712.01 秒；非进球动作时刻）
- 比分确认 **2:3**（记分牌锚点约 6881.94 秒；非进球动作时刻）

## 事件关系说明
- 叙事承接：各段按故事顺序衔接，**不代表**已证实战术因果。
- 时间先后：有时间戳的镜头按原片时间排序。
- 比分状态：score_path 相邻节点表示记分牌确认的比分变化。
- 事件关联：进球镜头与事件表/因果链 live 进球的规则匹配；**不等于**独立语义核验通过，也**不等于**已证实攻防因果。

## 镜头来源与核验状态（概要）
- 业务版与内部 QC 版共用同一剪辑时间轴（同一 EDL）。
- 全部镜头为算法候选：`render_ready=false`，未授予正式成片。
- 进球动作优先绑定事件表/因果链中的 live 进球时间；比分牌仅作确认，不替代进球。
- 完整进球动作候选 3 个；不完整/补证 0 个。

## 不能确认的关键事实与缺失证据
- 缺失证据标记：behind_carrier_unresolved:event_000456
- 缺失证据标记：equalizer_carrier_unresolved:event_000560
- 缺失证据标记：go_ahead_carrier_unresolved:event_000636
- 缺失证据标记：ending_match_end_rejected:match_end_too_far_after_final_score:dt=520.32

---

## 技术附录

以下字段供研发/算法复审，不作为甲方主读内容。完整图见 `story_graph.json`，剪辑表见 `candidate_edl.json`，方案见 `story_plan.json`。

- match_id: `10月27日_25-26赛季西甲第10轮_奥萨苏纳VS塞尔塔_国语`
- story_tier: `story`
- protagonist_side: `right`
- blocking_reasons: `['equalizer_goal_action_not_render_ready', 'go_ahead_goal_action_not_render_ready']`

| 段 | 叙事位 | 角色 | 原片入点 | 原片出点 | 关联事件 | 时间状态 | 进球完整 | 核验 |
|---|---|---|---|---|---|---|---|---|
| seg_title_open | 铺垫 | story_title | None | None | [] | placeholder_title | None | candidate_only / semantic_unverified |
| seg_opponent_opening_goal_action | 铺垫 | opponent_opening_goal_action | 3121.968 | 3143.968 | ['causal:ann_0014:event_000073'] | linked_event_ms | True | candidate_only / semantic_unverified |
| seg_setup_deficit | 铺垫 | deficit_scoreboard_anchor | 3198.66 | 3202.16 | [] | score_path_only | None | candidate_only / semantic_unverified |
| seg_buildup_event_000458 | 蓄力 | buildup_action | 3204.75 | 3216.75 | ['event_000458'] | event_ms | None | candidate_only / semantic_unverified |
| seg_buildup_event_000555 | 蓄力 | buildup_action | 5581.63 | 5593.63 | ['event_000555'] | event_ms | None | candidate_only / semantic_unverified |
| seg_equalizer_goal_action | 转折 | equalizer_goal_action | 5645.621 | 5667.621 | ['event_000117'] | linked_event_ms | True | candidate_only / semantic_unverified |
| seg_equalizer_scoreboard | 转折 | equalizer_scoreboard_anchor | 5711.01 | 5714.51 | [] | score_path_only | None | candidate_only / semantic_unverified |
| seg_go_ahead_goal_action | 高潮 | go_ahead_goal_action | 6779.882 | 6801.882 | ['causal:ann_0031:event_000160'] | linked_event_ms | True | candidate_only / semantic_unverified |
| seg_ending_final_scoreboard | 收尾 | ending_final_scoreboard | 6880.94 | 6884.44 | ['event_000636'] | score_path_only | None | candidate_only / semantic_unverified |
| seg_title_close | 收尾 | story_title | None | None | [] | placeholder_title | None | candidate_only / semantic_unverified |
