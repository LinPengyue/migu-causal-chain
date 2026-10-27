# Story Video Agent Phase 1.5 — 任务规划前后差异

## 法国 vs 澳大利亚

| | Phase 1 | Phase 1.5 |
|---|---|---|
| schema | story-video-agent-plan-1 | story-video-agent-plan-1.5 |
| gaps | ['verify_equalizer_scoreboard', 'verify_go_ahead_scoreboard', 'post_climax_reaction'] | ['verify_equalizer_goal_action', 'verify_equalizer_scoreboard', 'verify_go_ahead_goal_action', 'verify_go_ahead_scoreboard', 'post_climax_reaction'] |
| task statuses | planned×3 | ['pending', 'pending', 'pending', 'pending', 'pending'] |
| verification_complete | (implicit/untracked) | False |

关键 diffs:
- Phase1 scoreboard windows 贴进球事件(~2453/2883)；Phase1.5 OCR 用 score_path (2513.29 / 2904.31)，动作核实另开 `verify_*_goal_action` 用 goal_event。
- 新增 `verify_equalizer_goal_action` / `verify_go_ahead_goal_action`；反应窗改挂在进球锚点 2883.53 之后（不再误挂后期进球 5719）。
- 任务状态 `pending`，dry-run 不得 `verified`。

## 克罗地亚 vs 加拿大

| | Phase 1 | Phase 1.5 |
|---|---|---|
| schema | story-video-agent-plan-1 | story-video-agent-plan-1.5 |
| gaps | ['missing_setup_visual', 'missing_buildup_visual', 'verify_equalizer_scoreboard', 'verify_go_ahead_scoreboard', 'post_climax_reaction'] | ['missing_setup_visual', 'missing_buildup_visual', 'locate_go_ahead_goal_action', 'verify_equalizer_goal_action', 'verify_equalizer_scoreboard', 'verify_go_ahead_scoreboard', 'post_climax_reaction'] |
| task count | 5 | 7 |
| setup | 单窗 [1077.06, 1087.06] 贴首次比分 | search_intervals×35 adaptive_expand=True anchor=needs_search |
| buildup | 单窗中点附近 [5498.175, 5506.175] | search_intervals×30 needs_search |
- 反超缺进球锚点 → `locate_go_ahead_goal_action` (pending_localization)；扳平仍 `verify_equalizer_goal_action`。
- OCR 仍走 score_path；反应窗 `score_fallback_pending`。

## After task detail

### France
```
[
  {
    "gap_id": "verify_equalizer_goal_action",
    "status": "pending",
    "kind": "action_verify",
    "anchor_status": "goal_event",
    "score_anchor_sec": 2513.29,
    "goal_anchor_sec": 2453.099,
    "window": [
      2451.099,
      2461.099
    ],
    "n_intervals": 1,
    "adaptive_expand": true
  },
  {
    "gap_id": "verify_equalizer_scoreboard",
    "status": "pending",
    "kind": "scoreboard",
    "anchor_status": "score_path",
    "score_anchor_sec": 2513.29,
    "goal_anchor_sec": 2453.099,
    "window": [
      2511.29,
      2519.29
    ],
    "n_intervals": 1,
    "adaptive_expand": true
  },
  {
    "gap_id": "verify_go_ahead_goal_action",
    "status": "pending",
    "kind": "action_verify",
    "anchor_status": "goal_event",
    "score_anchor_sec": 2904.31,
    "goal_anchor_sec": 2883.53,
    "window": [
      2881.53,
      2891.53
    ],
    "n_intervals": 1,
    "adaptive_expand": true
  },
  {
    "gap_id": "verify_go_ahead_scoreboard",
    "status": "pending",
    "kind": "scoreboard",
    "anchor_status": "score_path",
    "score_anchor_sec": 2904.31,
    "goal_anchor_sec": 2883.53,
    "window": [
      2902.31,
      2910.31
    ],
    "n_intervals": 1,
    "adaptive_expand": true
  },
  {
    "gap_id": "post_climax_reaction",
    "status": "pending",
    "kind": "reaction",
    "anchor_status": "goal_event",
    "score_anchor_sec": 2904.31,
    "goal_anchor_sec": 2883.53,
    "window": [
      2883.53,
      2899.53
    ],
    "n_intervals": 1,
    "adaptive_expand": true
  }
]
```
### Croatia
```
[
  {
    "gap_id": "missing_setup_visual",
    "status": "pending",
    "kind": "setup",
    "anchor_status": "needs_search",
    "score_anchor_sec": 1079.06,
    "goal_anchor_sec": null,
    "window": [
      0.0,
      90.0
    ],
    "n_intervals": 35,
    "adaptive_expand": true
  },
  {
    "gap_id": "missing_buildup_visual",
    "status": "pending",
    "kind": "buildup",
    "anchor_status": "needs_search",
    "score_anchor_sec": null,
    "goal_anchor_sec": null,
    "window": [
      1079.06,
      1169.06
    ],
    "n_intervals": 30,
    "adaptive_expand": true
  },
  {
    "gap_id": "locate_go_ahead_goal_action",
    "status": "pending",
    "kind": "action_locate",
    "anchor_status": "pending_localization",
    "score_anchor_sec": 3697.35,
    "goal_anchor_sec": null,
    "window": [
      3577.35,
      3607.35
    ],
    "n_intervals": 5,
    "adaptive_expand": true
  },
  {
    "gap_id": "verify_equalizer_goal_action",
    "status": "pending",
    "kind": "action_verify",
    "anchor_status": "goal_event",
    "score_anchor_sec": 3145.98,
    "goal_anchor_sec": 3065.903,
    "window": [
      3063.903,
      3073.903
    ],
    "n_intervals": 1,
    "adaptive_expand": true
  },
  {
    "gap_id": "verify_equalizer_scoreboard",
    "status": "pending",
    "kind": "scoreboard",
    "anchor_status": "score_path",
    "score_anchor_sec": 3145.98,
    "goal_anchor_sec": 3065.903,
    "window": [
      3143.98,
      3151.98
    ],
    "n_intervals": 1,
    "adaptive_expand": true
  },
  {
    "gap_id": "verify_go_ahead_scoreboard",
    "status": "pending",
    "kind": "scoreboard",
    "anchor_status": "score_path",
    "score_anchor_sec": 3697.35,
    "goal_anchor_sec": null,
    "window": [
      3695.35,
      3703.35
    ],
    "n_intervals": 1,
    "adaptive_expand": true
  },
  {
    "gap_id": "post_climax_reaction",
    "status": "pending",
    "kind": "reaction",
    "anchor_status": "score_fallback_pending",
    "score_anchor_sec": 3697.35,
    "goal_anchor_sec": null,
    "window": [
      3697.35,
      3713.35
    ],
    "n_intervals": 1,
    "adaptive_expand": true
  }
]
```
