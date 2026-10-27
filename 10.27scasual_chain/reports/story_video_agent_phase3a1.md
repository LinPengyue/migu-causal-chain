# Phase 3A.1 Diff Report

## Verdict
事件溯源门禁生效：法国 `event_000027` 回放助攻不再挂到 1535s 落后铺垫；`score_path` 仅作比分锚点；`render_ready_edl` 在缺可信进球动作时为空。

## France 3A → 3A.1
- Old setup linked events: `[{'id': 'seg_setup_deficit', 'events': ['event_000027'], 'media_in': 1531.65, 'shot': 'live'}, {'id': 'seg_setup_replay_supp', 'events': ['event_000027'], 'media_in': 2446.817, 'shot': 'replay_supplement'}]`
- New setup excludes event_000027: `True`
- Old EDL treated score_path_only as include_in_cut count: `1`
- New render_ready_edl count: `0`
- Safe to cut: `[]`
- Blocked/draft: `['seg_setup_deficit', 'seg_buildup_event_000031', 'seg_buildup_event_000072', 'seg_equalizer_scoreboard', 'seg_equalizer_goal_pending', 'seg_go_ahead_scoreboard', 'seg_go_ahead_goal_pending', 'seg_ending']`

## Croatia
- render_ready: `False`
- blocking: `['equalizer_goal_action_not_render_ready', 'go_ahead_goal_action_not_render_ready', 'missing_trusted_goal_action:go_ahead']`

## none
- status: `blocked_none` · segments: `0`

## Artifacts
- `story_compose_phase3a1_{france,croatia,none}.json/.md`
- `*_candidate_edl.json` / `*_render_ready_edl.json`
- `story_video_agent_phase3a1_diff.json`
