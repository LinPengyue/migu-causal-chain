# 故事链内容摘要：克罗地亚 逆转 加拿大

> 内部候选交付 · `render_ready=false` · 非正式生产授权

## 1. 比赛信息与故事类型
- match_id: `2022-11-28 克罗地亚vs加拿大`
- 故事类型: T01 逆风翻盘（tier=`story`）
- 主角: 克罗地亚（left）
- 球队: left=克罗地亚 / right=加拿大

## 2. 故事标题
**克罗地亚 逆转 加拿大**

## 3. 故事摘要
本场由 T01 识别为逆风翻盘故事（tier=story），主角为 克罗地亚（side=left）。球队：克罗地亚 vs 加拿大。比分轨迹自 0:1 至终场相关节点 4:1（详见下表；记分牌时间为确认锚点，不等于进球动作时刻）。叙事按铺垫→蓄力→转折→高潮→收尾组织；进球镜头优先关联因果/事件表中的 live 进球，回放不作独立主叙事。以下摘要仅陈述系统已结构化收录的事件与关系，未经验证的因果不作事实断言。关键动作收录：铺垫段纳入 opponent_opening_goal_action（事件 ['event_000004']）；转折段纳入 equalizer_goal_action（事件 ['event_000021']）；高潮段纳入 go_ahead_goal_action（事件 ['event_000022']）；高潮段纳入 lead_extend_1_goal_action（事件 ['event_000025']）。

## 4. 五段叙事结构
### 铺垫
- **story_title** | media None-None | events=[] | phase5_narrative_packaging | status=placeholder_title / candidate_only
- **opponent_opening_goal_action** | media 968.137-990.137 | events=['event_000004'] | opponent_opening_goal_near_behind_scoreboard | status=linked_event_ms / candidate_only
- **deficit_scoreboard_anchor** | media 1078.06-1081.56 | events=['event_000004'] | last_comeback_arc_behind_start_score_path | status=score_path_only / candidate_only

### 蓄力
- **buildup_action** | media 1153.3-1165.3 | events=['event_000007'] | live_buildup_between_behind_and_equalizer | status=event_ms / candidate_only
- **buildup_action** | media 2200.2-2212.2 | events=['event_000040'] | live_buildup_between_behind_and_equalizer | status=event_ms / candidate_only

### 转折
- **equalizer_goal_action** | media 3053.903-3075.903 | events=['event_000021'] | live_goal_near_scoreboard_anchor | status=linked_event_ms / candidate_only
- **equalizer_scoreboard_anchor** | media 3144.98-3148.48 | events=[] | score_path_board_anchor | status=score_path_only / candidate_only

### 高潮
- **go_ahead_goal_action** | media 3511.574-3533.574 | events=['event_000022'] | live_goal_near_scoreboard_anchor | status=linked_event_ms / candidate_only
- **go_ahead_scoreboard_anchor** | media 3696.35-3699.85 | events=[] | score_path_board_anchor | status=score_path_only / candidate_only
- **lead_extend_1_goal_action** | media 6305.199-6315.8 | events=['event_000025'] | live_goal_near_scoreboard_anchor | status=linked_event_ms / candidate_only
- **lead_extend_1_scoreboard_anchor** | media 6407.7-6411.2 | events=[] | score_path_board_anchor | status=score_path_only / candidate_only
- **lead_extend_2_scoreboard_anchor** | media 7857.37-7860.87 | events=[] | score_path_board_anchor | status=score_path_only / candidate_only

### 收尾
- **ending** | media 7942.16-7954.16 | events=['event_000159'] | ending_event | status=event_ms / candidate_only
- **story_title** | media None-None | events=[] | phase5_narrative_packaging | status=placeholder_title / candidate_only

## 5. 关键比分变化
- 0:1 @ 1079.06s（delta_side=None）
- 1:1 @ 3145.98s（delta_side=left）
- 2:1 @ 3697.35s（delta_side=left）
- 3:1 @ 6408.7s（delta_side=left）
- 4:1 @ 7858.37s（delta_side=left）

## 6. 关键事件为何入选
- `seg_title_open`：phase5_narrative_packaging — 开场标题（不剧透终场比分）
- `seg_opponent_opening_goal_action`：opponent_opening_goal_near_behind_scoreboard — 率先失球动作 event_000004 @ 980.137s（相对 0:1 记分牌 Δ=-98.923s；非记分牌时间）。
- `seg_setup_deficit`：last_comeback_arc_behind_start_score_path — 比分确认落后 0:1 @ 1079.06s（非进球动作时间）。
- `seg_buildup_event_000007`：live_buildup_between_behind_and_equalizer — 蓄力动作 任意球（live，event_ms 未校准成片）。
- `seg_buildup_event_000040`：live_buildup_between_behind_and_equalizer — 蓄力动作 射门（live，event_ms 未校准成片）。
- `seg_equalizer_goal_action`：live_goal_near_scoreboard_anchor — equalizer 进球动作候选 event_000021 @ 3065.903s（相对记分牌 Δ=-80.077s）。
- `seg_equalizer_scoreboard`：score_path_board_anchor — equalizer 比分确认 1:1 @ 3145.98s（非进球剪辑点）。
- `seg_go_ahead_goal_action`：live_goal_near_scoreboard_anchor — go_ahead 进球动作候选 event_000022 @ 3523.574s（相对记分牌 Δ=-173.776s）。
- `seg_go_ahead_scoreboard`：score_path_board_anchor — go_ahead 比分确认 2:1 @ 3697.35s（非进球剪辑点）。
- `seg_lead_extend_1_goal_action`：live_goal_near_scoreboard_anchor — lead_extend_1 进球动作候选 event_000025 @ 6317.199s（相对记分牌 Δ=-91.501s）。
- `seg_lead_extend_1_scoreboard`：score_path_board_anchor — lead_extend_1 比分确认 3:1 @ 6408.7s（非进球剪辑点）。
- `seg_lead_extend_2_scoreboard`：score_path_board_anchor — lead_extend_2 比分确认 4:1 @ 7858.37s（非进球剪辑点）。
- `seg_ending`：ending_event — 收尾/终场（未校准默认不成片）。
- `seg_title_close`：phase5_narrative_packaging — 收束标题

## 7. 事件关系与证据（摘要）
关系类型详见 `story_graph.json`（因果 / 比分状态 / 时间先后 / 叙事承接分边）。
- 证据(rule_fact/opponent_opening_live_goal): {"kind": "rule_fact", "used_as_fact": true, "source": "opponent_opening_live_goal", "event_id": "event_000004", "dt_to_score_sec": -98.923, "note": "cause_of_deficit_not_scoreboard"}
- 证据(rule_fact/score_path): {"kind": "rule_fact", "used_as_fact": true, "source": "score_path", "score": "0:1", "t_sec": 1079.06, "note": "scoreboard_anchor_not_goal_action"}
- 证据(rule_fact/validated_carrier_link): {"kind": "rule_fact", "used_as_fact": true, "source": "validated_carrier_link", "event_id": "event_000004"}
- 证据(rule_fact/event): {"kind": "rule_fact", "used_as_fact": true, "source": "event", "event_id": "event_000007", "type": "任意球"}
- 证据(rule_fact/event): {"kind": "rule_fact", "used_as_fact": true, "source": "event", "event_id": "event_000040", "type": "射门"}
- 证据(rule_fact/live_goal_candidate): {"kind": "rule_fact", "used_as_fact": true, "source": "live_goal_candidate", "event_id": "event_000021", "dt_to_score_sec": -80.077}
- 证据(rule_fact/score_path): {"kind": "rule_fact", "used_as_fact": true, "source": "score_path", "score": "1:1", "t_sec": 3145.98, "note": "scoreboard_confirm_only"}
- 证据(rule_fact/live_goal_candidate): {"kind": "rule_fact", "used_as_fact": true, "source": "live_goal_candidate", "event_id": "event_000022", "dt_to_score_sec": -173.776}
- 证据(rule_fact/score_path): {"kind": "rule_fact", "used_as_fact": true, "source": "score_path", "score": "2:1", "t_sec": 3697.35, "note": "scoreboard_confirm_only"}
- 证据(rule_fact/live_goal_candidate): {"kind": "rule_fact", "used_as_fact": true, "source": "live_goal_candidate", "event_id": "event_000025", "dt_to_score_sec": -91.501}
- 证据(rule_fact/score_path): {"kind": "rule_fact", "used_as_fact": true, "source": "score_path", "score": "3:1", "t_sec": 6408.7, "note": "scoreboard_confirm_only"}
- 证据(rule_fact/score_path): {"kind": "rule_fact", "used_as_fact": true, "source": "score_path", "score": "4:1", "t_sec": 7858.37, "note": "scoreboard_confirm_only"}
- 证据(rule_fact/event): {"kind": "rule_fact", "used_as_fact": true, "source": "event", "event_id": "event_000159"}

## 8. 时间与核验
| segment | beat | media_in | media_out | events | time_status | eligibility |
|---|---|---|---|---|---|---|
| seg_title_open | 铺垫 | None | None | [] | placeholder_title | candidate_only |
| seg_opponent_opening_goal_action | 铺垫 | 968.137 | 990.137 | ['event_000004'] | linked_event_ms | candidate_only |
| seg_setup_deficit | 铺垫 | 1078.06 | 1081.56 | ['event_000004'] | score_path_only | candidate_only |
| seg_buildup_event_000007 | 蓄力 | 1153.3 | 1165.3 | ['event_000007'] | event_ms | candidate_only |
| seg_buildup_event_000040 | 蓄力 | 2200.2 | 2212.2 | ['event_000040'] | event_ms | candidate_only |
| seg_equalizer_goal_action | 转折 | 3053.903 | 3075.903 | ['event_000021'] | linked_event_ms | candidate_only |
| seg_equalizer_scoreboard | 转折 | 3144.98 | 3148.48 | [] | score_path_only | candidate_only |
| seg_go_ahead_goal_action | 高潮 | 3511.574 | 3533.574 | ['event_000022'] | linked_event_ms | candidate_only |
| seg_go_ahead_scoreboard | 高潮 | 3696.35 | 3699.85 | [] | score_path_only | candidate_only |
| seg_lead_extend_1_goal_action | 高潮 | 6305.199 | 6315.8 | ['event_000025'] | linked_event_ms | candidate_only |
| seg_lead_extend_1_scoreboard | 高潮 | 6407.7 | 6411.2 | [] | score_path_only | candidate_only |
| seg_lead_extend_2_scoreboard | 高潮 | 7857.37 | 7860.87 | [] | score_path_only | candidate_only |
| seg_ending | 收尾 | 7942.16 | 7954.16 | ['event_000159'] | event_ms | candidate_only |
| seg_title_close | 收尾 | None | None | [] | placeholder_title | candidate_only |

## 门禁
- render_ready: `False`
- blocking: ['equalizer_goal_action_not_render_ready', 'go_ahead_goal_action_not_render_ready', 'missing_trusted_goal_action:lead_extend_2']
- missing_evidence: ['equalizer_carrier_unresolved:event_000068', 'go_ahead_carrier_unresolved:event_000076', 'lead_extend_1_carrier_unresolved:event_000118', 'lead_extend_2_carrier_unresolved:event_000155', 'missing_live_goal_action:lead_extend_2']
