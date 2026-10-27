# T01 Story Plan — 2022年11月23日 法国vs澳大利亚
- tier: `story` · template: `T01_comeback`
- verification: `not_render_ready`
- structure_ok: `True` · render_ready: `False`
- protagonist: {'side': 'left', 'team_name': '法国', 'teams': {'left': '法国', 'right': '澳大利亚'}}

## Summary
法国 逆风翻盘草稿方案（3A.1）：比分锚点与进球动作分离；默认不可直接成片。

## Blocking (not render-ready)
- equalizer_goal_action_not_render_ready
- go_ahead_goal_action_not_render_ready
- missing_trusted_goal_action:equalizer
- missing_trusted_goal_action:go_ahead

## 铺垫
比分确认落后 0:1 @ 1535.65s（非进球动作时间）。
- `seg_setup_deficit` · shot=scoreboard_anchor · elig=candidate_only · time=score_path_only · in=1531.65 out=1543.65 · events=[] · conf=0.9
  - blocked: ['score_path_only_not_render_ready', 'setup_is_scoreboard_anchor_not_goal', 'unresolved_mapping:time_mismatch: event@2450.817s vs score@1535.650s dt=915.167s>120.0,type_incompatible:助攻,replay_far_from_scoreboard']
  - why: last_comeback_arc_behind_start_score_path
  - 比分确认落后 0:1 @ 1535.65s（非进球动作时间）。

## 蓄力
蓄力动作 角球（live，event_ms 未校准成片）。 蓄力动作 射门（live，event_ms 未校准成片）。
- `seg_buildup_event_000031` · shot=live · elig=candidate_only · time=event_ms · in=1585.9 out=1597.9 · events=['event_000031'] · conf=0.55
  - blocked: ['unverified_event_ms']
  - why: live_buildup_between_behind_and_equalizer
  - 蓄力动作 角球（live，event_ms 未校准成片）。
- `seg_buildup_event_000072` · shot=live · elig=candidate_only · time=event_ms · in=2107.89 out=2119.89 · events=['event_000072'] · conf=0.55
  - blocked: ['unverified_event_ms']
  - why: live_buildup_between_behind_and_equalizer
  - 蓄力动作 射门（live，event_ms 未校准成片）。

## 转折
equalizer 比分确认 1:1 @ 2513.29s（非进球剪辑点）。 equalizer 缺少可信 live 进球动作窗口；记分牌时间不可冒充进球。
- `seg_equalizer_scoreboard` · shot=scoreboard_anchor · elig=candidate_only · time=score_path_only · in=2509.29 out=2521.29 · events=[] · conf=0.85
  - blocked: ['score_path_only_not_render_ready']
  - why: score_path_board_anchor
  - equalizer 比分确认 1:1 @ 2513.29s（非进球剪辑点）。
- `seg_equalizer_goal_pending` · shot=unknown · elig=blocked · time=pending_localization · in=None out=None · events=[] · conf=0.0
  - blocked: ['missing_trusted_goal_action:equalizer']
  - why: no_live_goal_candidate_near_scoreboard
  - equalizer 缺少可信 live 进球动作窗口；记分牌时间不可冒充进球。

## 高潮
go_ahead 比分确认 2:1 @ 2904.31s（非进球剪辑点）。 go_ahead 缺少可信 live 进球动作窗口；记分牌时间不可冒充进球。
- `seg_go_ahead_scoreboard` · shot=scoreboard_anchor · elig=candidate_only · time=score_path_only · in=2900.31 out=2912.31 · events=[] · conf=0.85
  - blocked: ['score_path_only_not_render_ready']
  - why: score_path_board_anchor
  - go_ahead 比分确认 2:1 @ 2904.31s（非进球剪辑点）。
- `seg_go_ahead_goal_pending` · shot=unknown · elig=blocked · time=pending_localization · in=None out=None · events=[] · conf=0.0
  - blocked: ['missing_trusted_goal_action:go_ahead']
  - why: no_live_goal_candidate_near_scoreboard
  - go_ahead 缺少可信 live 进球动作窗口；记分牌时间不可冒充进球。

## 收尾
收尾/终场（未校准默认不成片）。
- `seg_ending` · shot=live · elig=candidate_only · time=event_ms · in=7237.8 out=7249.8 · events=['event_000302'] · conf=0.5
  - blocked: ['unverified_event_ms']
  - why: ending_event
  - 收尾/终场（未校准默认不成片）。

## Render-ready EDL
(empty — not safe to cut)

## Candidate EDL (draft only)
- #1 铺垫 elig=candidate_only [1531.65, 1543.65] score_path_only
- #2 蓄力 elig=candidate_only [1585.9, 1597.9] event_ms
- #3 蓄力 elig=candidate_only [2107.89, 2119.89] event_ms
- #4 转折 elig=candidate_only [2509.29, 2521.29] score_path_only
- #5 转折 elig=blocked [None, None] pending_localization
- #6 高潮 elig=candidate_only [2900.31, 2912.31] score_path_only
- #7 高潮 elig=blocked [None, None] pending_localization
- #8 收尾 elig=candidate_only [7237.8, 7249.8] event_ms
