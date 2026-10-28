# QC 证据包：croatia

> 自动抽帧仅供人工审片。**不构成**语义核验通过。`render_ready` 仍为 false。

## 检查项说明
- 进球锚点是否落在裁剪窗口内
- 是否误用比分牌/回放充当进球直播（需看图）
- 是否保留进攻上下文（需看图）
- 花屏避让是否破坏进球完整性（见 goal_action_complete）
- Summary / Graph / EDL / 视频一致性（对照同目录产物）

### seg_opponent_opening_goal_action · opponent_opening_goal_action
- 窗口 `968.137`–`990.137` · anchor=980.137 · complete=True
- checklist: `{"goal_inside_window": true, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=969.14 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_opponent_opening_goal_action_in_plus_1_969.1.jpg`
- [OK] t=979.14 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_opponent_opening_goal_action_mid_979.1.jpg`
- [OK] t=989.14 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_opponent_opening_goal_action_out_minus_1_989.1.jpg`
- [OK] t=980.14 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_opponent_opening_goal_action_anchor_980.1.jpg`
- [OK] t=981.64 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_opponent_opening_goal_action_anchor_plus_1_5_981.6.jpg`

### seg_setup_deficit · deficit_scoreboard_anchor
- 窗口 `1078.060`–`1081.560` · anchor=None · complete=None
- checklist: `{"goal_inside_window": null, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=1079.06 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_setup_deficit_in_plus_1_1079.1.jpg`
- [OK] t=1079.81 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_setup_deficit_mid_1079.8.jpg`
- [OK] t=1080.56 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_setup_deficit_out_minus_1_1080.6.jpg`

### seg_equalizer_goal_action · equalizer_goal_action
- 窗口 `3053.903`–`3075.903` · anchor=3065.903 · complete=True
- checklist: `{"goal_inside_window": true, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=3054.90 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_equalizer_goal_action_in_plus_1_3054.9.jpg`
- [OK] t=3064.90 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_equalizer_goal_action_mid_3064.9.jpg`
- [OK] t=3074.90 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_equalizer_goal_action_out_minus_1_3074.9.jpg`
- [OK] t=3065.90 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_equalizer_goal_action_anchor_3065.9.jpg`
- [OK] t=3067.40 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_equalizer_goal_action_anchor_plus_1_5_3067.4.jpg`

### seg_go_ahead_goal_action · go_ahead_goal_action
- 窗口 `3511.574`–`3533.574` · anchor=3523.574 · complete=True
- checklist: `{"goal_inside_window": true, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=3512.57 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_go_ahead_goal_action_in_plus_1_3512.6.jpg`
- [OK] t=3522.57 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_go_ahead_goal_action_mid_3522.6.jpg`
- [OK] t=3532.57 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_go_ahead_goal_action_out_minus_1_3532.6.jpg`
- [OK] t=3523.57 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_go_ahead_goal_action_anchor_3523.6.jpg`
- [OK] t=3525.07 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_go_ahead_goal_action_anchor_plus_1_5_3525.1.jpg`

### seg_lead_extend_1_goal_action_approach · lead_extend_1_goal_action_approach
- 窗口 `6305.199`–`6315.800` · anchor=6317.199 · complete=True
- checklist: `{"goal_inside_window": false, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=6306.20 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_lead_extend_1_goal_action_approach_in_plus_1_6306.2.jpg`
- [OK] t=6310.50 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_lead_extend_1_goal_action_approach_mid_6310.5.jpg`
- [OK] t=6314.80 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_lead_extend_1_goal_action_approach_out_minus_1_6314.8.jpg`
- [OK] t=6317.20 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_lead_extend_1_goal_action_approach_anchor_6317.2.jpg`
- [OK] t=6318.70 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_lead_extend_1_goal_action_approach_anchor_plus_1_5_6318.7.jpg`

### seg_lead_extend_1_goal_action · lead_extend_1_goal_action
- 窗口 `6316.700`–`6327.199` · anchor=6317.199 · complete=True
- checklist: `{"goal_inside_window": true, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=6317.70 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_lead_extend_1_goal_action_in_plus_1_6317.7.jpg`
- [OK] t=6321.95 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_lead_extend_1_goal_action_mid_6321.9.jpg`
- [OK] t=6326.20 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_lead_extend_1_goal_action_out_minus_1_6326.2.jpg`
- [OK] t=6317.20 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_lead_extend_1_goal_action_anchor_6317.2.jpg`
- [OK] t=6318.70 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_lead_extend_1_goal_action_anchor_plus_1_5_6318.7.jpg`

### seg_lead_extend_1_scoreboard · lead_extend_1_scoreboard_anchor
- 窗口 `6407.700`–`6411.200` · anchor=None · complete=None
- checklist: `{"goal_inside_window": null, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=6408.70 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_lead_extend_1_scoreboard_in_plus_1_6408.7.jpg`
- [OK] t=6409.45 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_lead_extend_1_scoreboard_mid_6409.4.jpg`
- [OK] t=6410.20 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/qc_pack/frames/seg_lead_extend_1_scoreboard_out_minus_1_6410.2.jpg`

