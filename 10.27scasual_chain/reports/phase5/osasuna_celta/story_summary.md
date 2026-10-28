# 故事链内容摘要：塞尔塔维戈 逆转 奥萨苏纳

> 内部候选交付 · `render_ready=false` · 非正式生产授权

## 1. 比赛信息与故事类型
- match_id: `10月27日_25-26赛季西甲第10轮_奥萨苏纳VS塞尔塔_国语`
- 故事类型: T01 逆风翻盘（tier=`story`）
- 主角: 塞尔塔维戈（right）
- 球队: left=奥萨苏纳 / right=塞尔塔维戈

## 2. 故事标题
**塞尔塔维戈 逆转 奥萨苏纳**

## 3. 故事摘要
本场由 T01 识别为逆风翻盘故事（tier=story），主角为 塞尔塔维戈（side=right）。球队：奥萨苏纳 vs 塞尔塔维戈。比分轨迹自 0:0 至终场相关节点 2:3（详见下表；记分牌时间为确认锚点，不等于进球动作时刻）。叙事按铺垫→蓄力→转折→高潮→收尾组织；进球镜头优先关联因果/事件表中的 live 进球，回放不作独立主叙事。以下摘要仅陈述系统已结构化收录的事件与关系，未经验证的因果不作事实断言。关键动作收录：铺垫段纳入 opponent_opening_goal_action（事件 ['causal:ann_0014:event_000073']）；转折段纳入 equalizer_goal_action（事件 ['event_000117']）；高潮段纳入 go_ahead_goal_action（事件 ['causal:ann_0031:event_000160']）。

## 4. 五段叙事结构
### 铺垫
- **story_title** | media None-None | events=[] | phase5_narrative_packaging | status=placeholder_title / candidate_only
- **opponent_opening_goal_action** | media 3121.968-3143.968 | events=['causal:ann_0014:event_000073'] | opponent_opening_goal_near_behind_scoreboard | status=linked_event_ms / candidate_only
- **deficit_scoreboard_anchor** | media 3198.66-3202.16 | events=[] | last_comeback_arc_behind_start_score_path | status=score_path_only / candidate_only

### 蓄力
- **buildup_action** | media 3204.75-3216.75 | events=['event_000458'] | live_buildup_between_behind_and_equalizer | status=event_ms / candidate_only
- **buildup_action** | media 5581.63-5593.63 | events=['event_000555'] | live_buildup_between_behind_and_equalizer | status=event_ms / candidate_only

### 转折
- **equalizer_goal_action** | media 5645.621-5667.621 | events=['event_000117'] | live_goal_near_scoreboard_anchor | status=linked_event_ms / candidate_only
- **equalizer_scoreboard_anchor** | media 5711.01-5714.51 | events=[] | score_path_board_anchor | status=score_path_only / candidate_only

### 高潮
- **go_ahead_goal_action** | media 6779.882-6801.882 | events=['causal:ann_0031:event_000160'] | live_goal_near_scoreboard_anchor | status=linked_event_ms / candidate_only
- **go_ahead_scoreboard_anchor** | media 6880.94-6884.44 | events=[] | score_path_board_anchor | status=score_path_only / candidate_only

### 收尾
- **ending** | media 7398.26-7410.26 | events=['event_000663'] | ending_event | status=event_ms / candidate_only
- **story_title** | media None-None | events=[] | phase5_narrative_packaging | status=placeholder_title / candidate_only

## 5. 关键比分变化
- 0:0 @ 425.71s（delta_side=None）
- 0:1 @ 2071.43s（delta_side=right）
- 1:1 @ 2660.82s（delta_side=left）
- 2:1 @ 3199.66s（delta_side=left）
- 2:2 @ 5712.01s（delta_side=right）
- 2:3 @ 6881.94s（delta_side=right）

## 6. 关键事件为何入选
- `seg_title_open`：phase5_narrative_packaging — 开场标题（不剧透终场比分）
- `seg_opponent_opening_goal_action`：opponent_opening_goal_near_behind_scoreboard — 率先失球动作 causal:ann_0014:event_000073 @ 3133.968s（相对 0:1 记分牌 Δ=-65.692s；非记分牌时间）。
- `seg_setup_deficit`：last_comeback_arc_behind_start_score_path — 比分确认落后 2:1 @ 3199.66s（非进球动作时间）。
- `seg_buildup_event_000458`：live_buildup_between_behind_and_equalizer — 蓄力动作 射门（live，event_ms 未校准成片）。
- `seg_buildup_event_000555`：live_buildup_between_behind_and_equalizer — 蓄力动作 任意球（live，event_ms 未校准成片）。
- `seg_equalizer_goal_action`：live_goal_near_scoreboard_anchor — equalizer 进球动作候选 event_000117 @ 5657.621s（相对记分牌 Δ=-54.389s）。
- `seg_equalizer_scoreboard`：score_path_board_anchor — equalizer 比分确认 2:2 @ 5712.01s（非进球剪辑点）。
- `seg_go_ahead_goal_action`：live_goal_near_scoreboard_anchor — go_ahead 进球动作候选 causal:ann_0031:event_000160 @ 6791.882s（相对记分牌 Δ=-90.058s）。
- `seg_go_ahead_scoreboard`：score_path_board_anchor — go_ahead 比分确认 2:3 @ 6881.94s（非进球剪辑点）。
- `seg_ending`：ending_event — 收尾/终场（未校准默认不成片）。
- `seg_title_close`：phase5_narrative_packaging — 收束标题

## 7. 事件关系与证据（摘要）
关系类型详见 `story_graph.json`（因果 / 比分状态 / 时间先后 / 叙事承接分边）。
- 证据(rule_fact/opponent_opening_live_goal): {"kind": "rule_fact", "used_as_fact": true, "source": "opponent_opening_live_goal", "event_id": "causal:ann_0014:event_000073", "dt_to_score_sec": -65.692, "note": "cause_of_deficit_not_scoreboard"}
- 证据(rule_fact/score_path): {"kind": "rule_fact", "used_as_fact": true, "source": "score_path", "score": "2:1", "t_sec": 3199.66, "note": "scoreboard_anchor_not_goal_action"}
- 证据(rule_fact/event): {"kind": "rule_fact", "used_as_fact": true, "source": "event", "event_id": "event_000458", "type": "射门"}
- 证据(rule_fact/event): {"kind": "rule_fact", "used_as_fact": true, "source": "event", "event_id": "event_000555", "type": "任意球"}
- 证据(rule_fact/live_goal_candidate): {"kind": "rule_fact", "used_as_fact": true, "source": "live_goal_candidate", "event_id": "event_000117", "dt_to_score_sec": -54.389}
- 证据(rule_fact/score_path): {"kind": "rule_fact", "used_as_fact": true, "source": "score_path", "score": "2:2", "t_sec": 5712.01, "note": "scoreboard_confirm_only"}
- 证据(rule_fact/live_goal_candidate): {"kind": "rule_fact", "used_as_fact": true, "source": "live_goal_candidate", "event_id": "causal:ann_0031:event_000160", "dt_to_score_sec": -90.058}
- 证据(rule_fact/score_path): {"kind": "rule_fact", "used_as_fact": true, "source": "score_path", "score": "2:3", "t_sec": 6881.94, "note": "scoreboard_confirm_only"}
- 证据(rule_fact/event): {"kind": "rule_fact", "used_as_fact": true, "source": "event", "event_id": "event_000663"}

## 8. 时间与核验
| segment | beat | media_in | media_out | events | time_status | eligibility |
|---|---|---|---|---|---|---|
| seg_title_open | 铺垫 | None | None | [] | placeholder_title | candidate_only |
| seg_opponent_opening_goal_action | 铺垫 | 3121.968 | 3143.968 | ['causal:ann_0014:event_000073'] | linked_event_ms | candidate_only |
| seg_setup_deficit | 铺垫 | 3198.66 | 3202.16 | [] | score_path_only | candidate_only |
| seg_buildup_event_000458 | 蓄力 | 3204.75 | 3216.75 | ['event_000458'] | event_ms | candidate_only |
| seg_buildup_event_000555 | 蓄力 | 5581.63 | 5593.63 | ['event_000555'] | event_ms | candidate_only |
| seg_equalizer_goal_action | 转折 | 5645.621 | 5667.621 | ['event_000117'] | linked_event_ms | candidate_only |
| seg_equalizer_scoreboard | 转折 | 5711.01 | 5714.51 | [] | score_path_only | candidate_only |
| seg_go_ahead_goal_action | 高潮 | 6779.882 | 6801.882 | ['causal:ann_0031:event_000160'] | linked_event_ms | candidate_only |
| seg_go_ahead_scoreboard | 高潮 | 6880.94 | 6884.44 | [] | score_path_only | candidate_only |
| seg_ending | 收尾 | 7398.26 | 7410.26 | ['event_000663'] | event_ms | candidate_only |
| seg_title_close | 收尾 | None | None | [] | placeholder_title | candidate_only |

## 门禁
- render_ready: `False`
- blocking: ['equalizer_goal_action_not_render_ready', 'go_ahead_goal_action_not_render_ready']
- missing_evidence: ['behind_carrier_unresolved:event_000456', 'equalizer_carrier_unresolved:event_000560', 'go_ahead_carrier_unresolved:event_000636']
