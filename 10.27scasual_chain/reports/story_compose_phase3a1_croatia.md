# T01 Story Plan — 2022-11-28 克罗地亚vs加拿大
- tier: `candidate` · template: `T01_comeback`
- verification: `not_render_ready`
- structure_ok: `True` · render_ready: `False`
- protagonist: {'side': 'left', 'team_name': '克罗地亚', 'teams': {'left': '克罗地亚', 'right': '加拿大'}}

## Summary
克罗地亚 翻盘候选不完整；见 missing_evidence / blocking_reasons。

## Blocking (not render-ready)
- equalizer_goal_action_not_render_ready
- go_ahead_goal_action_not_render_ready
- missing_trusted_goal_action:go_ahead

## 铺垫
比分确认落后 0:1 @ 1079.06s（非进球动作时间）。
- `seg_setup_deficit` · shot=scoreboard_anchor · elig=candidate_only · time=score_path_only · in=1075.06 out=1087.06 · events=[] · conf=0.9
  - blocked: ['score_path_only_not_render_ready', 'setup_is_scoreboard_anchor_not_goal', 'unresolved_mapping:carrier_id_not_in_story_events']
  - why: last_comeback_arc_behind_start_score_path
  - 比分确认落后 0:1 @ 1079.06s（非进球动作时间）。

## 蓄力


## 转折
equalizer 进球动作候选 event_000021 @ 3065.903s（相对记分牌 Δ=-80.077s）。 equalizer 比分确认 1:1 @ 3145.98s（非进球剪辑点）。
- `seg_equalizer_goal_action` · shot=live · elig=candidate_only · time=linked_event_ms · in=3061.903 out=3073.903 · events=['event_000021'] · conf=0.333
  - blocked: ['goal_action_time_not_pipeline_verified']
  - why: live_goal_near_scoreboard_anchor
  - equalizer 进球动作候选 event_000021 @ 3065.903s（相对记分牌 Δ=-80.077s）。
- `seg_equalizer_scoreboard` · shot=scoreboard_anchor · elig=candidate_only · time=score_path_only · in=3141.98 out=3153.98 · events=[] · conf=0.85
  - blocked: ['score_path_only_not_render_ready']
  - why: score_path_board_anchor
  - equalizer 比分确认 1:1 @ 3145.98s（非进球剪辑点）。

## 高潮
go_ahead 比分确认 2:1 @ 3697.35s（非进球剪辑点）。 go_ahead 缺少可信 live 进球动作窗口；记分牌时间不可冒充进球。
- `seg_go_ahead_scoreboard` · shot=scoreboard_anchor · elig=candidate_only · time=score_path_only · in=3693.35 out=3705.35 · events=[] · conf=0.85
  - blocked: ['score_path_only_not_render_ready']
  - why: score_path_board_anchor
  - go_ahead 比分确认 2:1 @ 3697.35s（非进球剪辑点）。
- `seg_go_ahead_goal_pending` · shot=unknown · elig=blocked · time=pending_localization · in=None out=None · events=[] · conf=0.0
  - blocked: ['missing_trusted_goal_action:go_ahead']
  - why: no_live_goal_candidate_near_scoreboard
  - go_ahead 缺少可信 live 进球动作窗口；记分牌时间不可冒充进球。

## 收尾
收尾/终场（未校准默认不成片）。
- `seg_ending` · shot=live · elig=candidate_only · time=event_ms · in=7942.16 out=7954.16 · events=['event_000159'] · conf=0.5
  - blocked: ['unverified_event_ms']
  - why: ending_event
  - 收尾/终场（未校准默认不成片）。

## Render-ready EDL
(empty — not safe to cut)

## Candidate EDL (draft only)
- #1 铺垫 elig=candidate_only [1075.06, 1087.06] score_path_only
- #2 转折 elig=candidate_only [3061.903, 3073.903] linked_event_ms
- #3 转折 elig=candidate_only [3141.98, 3153.98] score_path_only
- #4 高潮 elig=candidate_only [3693.35, 3705.35] score_path_only
- #5 高潮 elig=blocked [None, None] pending_localization
- #6 收尾 elig=candidate_only [7942.16, 7954.16] event_ms
