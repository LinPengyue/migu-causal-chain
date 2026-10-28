# 故事链内容摘要：阿联酋 逆转 阿曼

> 内部候选交付 · `render_ready=false` · 非正式生产授权

## 1. 比赛信息与故事类型
- match_id: `10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语`
- 故事类型: T01 逆风翻盘（tier=`story`）
- 主角: 阿联酋（left）
- 球队: left=阿联酋 / right=阿曼

## 2. 故事标题
**阿联酋 逆转 阿曼**

## 3. 故事摘要
本场由 T01 识别为逆风翻盘故事（tier=story），主角为 阿联酋（side=left）。球队：阿联酋 vs 阿曼。比分轨迹自 0:0 至终场相关节点 2:1（详见下表；记分牌时间为确认锚点，不等于进球动作时刻）。叙事按铺垫→蓄力→转折→高潮→收尾组织；进球镜头优先关联因果/事件表中的 live 进球，回放不作独立主叙事。以下摘要仅陈述系统已结构化收录的事件与关系，未经验证的因果不作事实断言。关键动作收录：铺垫段纳入 opponent_opening_goal_action（事件 ['causal:ann_0001:event_000005']）；转折段纳入 equalizer_goal_action（事件 ['causal:ann_0015:event_000076']）；高潮段纳入 go_ahead_goal_action（事件 ['causal:ann_0020:event_000105']）。

## 4. 五段叙事结构
### 铺垫
- **story_title** | media None-None | events=[] | phase5_narrative_packaging | status=placeholder_title / candidate_only
- **opponent_opening_goal_action** | media 1325.123-1347.123 | events=['causal:ann_0001:event_000005'] | opponent_opening_goal_near_behind_scoreboard | status=linked_event_ms / candidate_only
- **deficit_scoreboard_anchor** | media 1409.43-1412.93 | events=[] | last_comeback_arc_behind_start_score_path | status=score_path_only / candidate_only

### 蓄力
- **buildup_action** | media 1912.42-1924.42 | events=['event_000276'] | live_buildup_between_behind_and_equalizer | status=event_ms / candidate_only
- **buildup_action** | media 3442.75-3454.75 | events=['event_000411'] | live_buildup_between_behind_and_equalizer | status=event_ms / candidate_only

### 转折
- **equalizer_goal_action** | media 6437.644-6459.644 | events=['causal:ann_0015:event_000076'] | live_goal_near_scoreboard_anchor | status=linked_event_ms / candidate_only
- **equalizer_scoreboard_anchor** | media 6534.62-6538.12 | events=[] | score_path_board_anchor | status=score_path_only / candidate_only

### 高潮
- **go_ahead_goal_action** | media 6831.088-6853.088 | events=['causal:ann_0020:event_000105'] | live_goal_near_scoreboard_anchor | status=linked_event_ms / candidate_only
- **go_ahead_scoreboard_anchor** | media 6956.12-6959.62 | events=[] | score_path_board_anchor | status=score_path_only / candidate_only

### 收尾
- **ending** | media 8008.93-8020.93 | events=['event_000749'] | ending_event | status=event_ms / candidate_only
- **story_title** | media None-None | events=[] | phase5_narrative_packaging | status=placeholder_title / candidate_only

## 5. 关键比分变化
- 0:0 @ 649.75s（delta_side=None）
- 0:1 @ 1410.43s（delta_side=right）
- 1:1 @ 6535.62s（delta_side=left）
- 2:1 @ 6957.12s（delta_side=left）

## 6. 关键事件为何入选
- `seg_title_open`：phase5_narrative_packaging — 开场标题（不剧透终场比分）
- `seg_opponent_opening_goal_action`：opponent_opening_goal_near_behind_scoreboard — 率先失球动作 causal:ann_0001:event_000005 @ 1337.123s（相对 0:1 记分牌 Δ=-73.307s；非记分牌时间）。
- `seg_setup_deficit`：last_comeback_arc_behind_start_score_path — 比分确认落后 0:1 @ 1410.43s（非进球动作时间）。
- `seg_buildup_event_000276`：live_buildup_between_behind_and_equalizer — 蓄力动作 角球（live，event_ms 未校准成片）。
- `seg_buildup_event_000411`：live_buildup_between_behind_and_equalizer — 蓄力动作 射门（live，event_ms 未校准成片）。
- `seg_equalizer_goal_action`：live_goal_near_scoreboard_anchor — equalizer 进球动作候选 causal:ann_0015:event_000076 @ 6449.644s（相对记分牌 Δ=-85.976s）。
- `seg_equalizer_scoreboard`：score_path_board_anchor — equalizer 比分确认 1:1 @ 6535.62s（非进球剪辑点）。
- `seg_go_ahead_goal_action`：live_goal_near_scoreboard_anchor — go_ahead 进球动作候选 causal:ann_0020:event_000105 @ 6843.088s（相对记分牌 Δ=-114.032s）。
- `seg_go_ahead_scoreboard`：score_path_board_anchor — go_ahead 比分确认 2:1 @ 6957.12s（非进球剪辑点）。
- `seg_ending`：ending_event — 收尾/终场（未校准默认不成片）。
- `seg_title_close`：phase5_narrative_packaging — 收束标题

## 7. 事件关系与证据（摘要）
关系类型详见 `story_graph.json`（因果 / 比分状态 / 时间先后 / 叙事承接分边）。
- 证据(rule_fact/opponent_opening_live_goal): {"kind": "rule_fact", "used_as_fact": true, "source": "opponent_opening_live_goal", "event_id": "causal:ann_0001:event_000005", "dt_to_score_sec": -73.307, "note": "cause_of_deficit_not_scoreboard"}
- 证据(rule_fact/score_path): {"kind": "rule_fact", "used_as_fact": true, "source": "score_path", "score": "0:1", "t_sec": 1410.43, "note": "scoreboard_anchor_not_goal_action"}
- 证据(rule_fact/event): {"kind": "rule_fact", "used_as_fact": true, "source": "event", "event_id": "event_000276", "type": "角球"}
- 证据(rule_fact/event): {"kind": "rule_fact", "used_as_fact": true, "source": "event", "event_id": "event_000411", "type": "射门"}
- 证据(rule_fact/live_goal_candidate): {"kind": "rule_fact", "used_as_fact": true, "source": "live_goal_candidate", "event_id": "causal:ann_0015:event_000076", "dt_to_score_sec": -85.976}
- 证据(rule_fact/score_path): {"kind": "rule_fact", "used_as_fact": true, "source": "score_path", "score": "1:1", "t_sec": 6535.62, "note": "scoreboard_confirm_only"}
- 证据(rule_fact/live_goal_candidate): {"kind": "rule_fact", "used_as_fact": true, "source": "live_goal_candidate", "event_id": "causal:ann_0020:event_000105", "dt_to_score_sec": -114.032}
- 证据(rule_fact/score_path): {"kind": "rule_fact", "used_as_fact": true, "source": "score_path", "score": "2:1", "t_sec": 6957.12, "note": "scoreboard_confirm_only"}
- 证据(rule_fact/event): {"kind": "rule_fact", "used_as_fact": true, "source": "event", "event_id": "event_000749"}

## 8. 时间与核验
| segment | beat | media_in | media_out | events | time_status | eligibility |
|---|---|---|---|---|---|---|
| seg_title_open | 铺垫 | None | None | [] | placeholder_title | candidate_only |
| seg_opponent_opening_goal_action | 铺垫 | 1325.123 | 1347.123 | ['causal:ann_0001:event_000005'] | linked_event_ms | candidate_only |
| seg_setup_deficit | 铺垫 | 1409.43 | 1412.93 | [] | score_path_only | candidate_only |
| seg_buildup_event_000276 | 蓄力 | 1912.42 | 1924.42 | ['event_000276'] | event_ms | candidate_only |
| seg_buildup_event_000411 | 蓄力 | 3442.75 | 3454.75 | ['event_000411'] | event_ms | candidate_only |
| seg_equalizer_goal_action | 转折 | 6437.644 | 6459.644 | ['causal:ann_0015:event_000076'] | linked_event_ms | candidate_only |
| seg_equalizer_scoreboard | 转折 | 6534.62 | 6538.12 | [] | score_path_only | candidate_only |
| seg_go_ahead_goal_action | 高潮 | 6831.088 | 6853.088 | ['causal:ann_0020:event_000105'] | linked_event_ms | candidate_only |
| seg_go_ahead_scoreboard | 高潮 | 6956.12 | 6959.62 | [] | score_path_only | candidate_only |
| seg_ending | 收尾 | 8008.93 | 8020.93 | ['event_000749'] | event_ms | candidate_only |
| seg_title_close | 收尾 | None | None | [] | placeholder_title | candidate_only |

## 门禁
- render_ready: `False`
- blocking: ['equalizer_goal_action_not_render_ready', 'go_ahead_goal_action_not_render_ready']
- missing_evidence: ['behind_carrier_unresolved:event_000173', 'equalizer_carrier_unresolved:event_000637', 'go_ahead_carrier_unresolved:event_000670']
