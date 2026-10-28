# QC 证据包：osasuna_celta

> 自动抽帧仅供人工审片。**不构成**语义核验通过。`render_ready` 仍为 false。

## 检查项说明
- 进球锚点是否落在裁剪窗口内
- 是否误用比分牌/回放充当进球直播（需看图）
- 是否保留进攻上下文（需看图）
- 花屏避让是否破坏进球完整性（见 goal_action_complete）
- Summary / Graph / EDL / 视频一致性（对照同目录产物）

### seg_opponent_opening_goal_action · opponent_opening_goal_action
- 窗口 `3121.968`–`3143.968` · anchor=3133.968 · complete=True
- checklist: `{"goal_inside_window": true, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=3122.97 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_opponent_opening_goal_action_in_plus_1_3123.0.jpg`
- [OK] t=3132.97 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_opponent_opening_goal_action_mid_3133.0.jpg`
- [OK] t=3142.97 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_opponent_opening_goal_action_out_minus_1_3143.0.jpg`
- [OK] t=3133.97 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_opponent_opening_goal_action_anchor_3134.0.jpg`
- [OK] t=3135.47 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_opponent_opening_goal_action_anchor_plus_1_5_3135.5.jpg`

### seg_setup_deficit · deficit_scoreboard_anchor
- 窗口 `3198.660`–`3202.160` · anchor=None · complete=None
- checklist: `{"goal_inside_window": null, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=3199.66 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_setup_deficit_in_plus_1_3199.7.jpg`
- [OK] t=3200.41 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_setup_deficit_mid_3200.4.jpg`
- [OK] t=3201.16 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_setup_deficit_out_minus_1_3201.2.jpg`

### seg_equalizer_goal_action · equalizer_goal_action
- 窗口 `5645.621`–`5667.621` · anchor=5657.621 · complete=True
- checklist: `{"goal_inside_window": true, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=5646.62 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_equalizer_goal_action_in_plus_1_5646.6.jpg`
- [OK] t=5656.62 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_equalizer_goal_action_mid_5656.6.jpg`
- [OK] t=5666.62 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_equalizer_goal_action_out_minus_1_5666.6.jpg`
- [OK] t=5657.62 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_equalizer_goal_action_anchor_5657.6.jpg`
- [OK] t=5659.12 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_equalizer_goal_action_anchor_plus_1_5_5659.1.jpg`

### seg_go_ahead_goal_action · go_ahead_goal_action
- 窗口 `6779.882`–`6801.882` · anchor=6791.882 · complete=True
- checklist: `{"goal_inside_window": true, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=6780.88 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_go_ahead_goal_action_in_plus_1_6780.9.jpg`
- [OK] t=6790.88 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_go_ahead_goal_action_mid_6790.9.jpg`
- [OK] t=6800.88 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_go_ahead_goal_action_out_minus_1_6800.9.jpg`
- [OK] t=6791.88 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_go_ahead_goal_action_anchor_6791.9.jpg`
- [OK] t=6793.38 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/osasuna_celta/qc_pack/frames/seg_go_ahead_goal_action_anchor_plus_1_5_6793.4.jpg`

