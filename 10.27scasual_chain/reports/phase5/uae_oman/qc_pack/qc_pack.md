# QC 证据包：uae_oman

> 自动抽帧仅供人工审片。**不构成**语义核验通过。`render_ready` 仍为 false。

## 检查项说明
- 进球锚点是否落在裁剪窗口内
- 是否误用比分牌/回放充当进球直播（需看图）
- 是否保留进攻上下文（需看图）
- 花屏避让是否破坏进球完整性（见 goal_action_complete）
- Summary / Graph / EDL / 视频一致性（对照同目录产物）

### seg_opponent_opening_goal_action · opponent_opening_goal_action
- 窗口 `1325.123`–`1347.123` · anchor=1337.123 · complete=True
- checklist: `{"goal_inside_window": true, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=1326.12 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_opponent_opening_goal_action_in_plus_1_1326.1.jpg`
- [OK] t=1336.12 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_opponent_opening_goal_action_mid_1336.1.jpg`
- [OK] t=1346.12 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_opponent_opening_goal_action_out_minus_1_1346.1.jpg`
- [OK] t=1337.12 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_opponent_opening_goal_action_anchor_1337.1.jpg`
- [OK] t=1338.62 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_opponent_opening_goal_action_anchor_plus_1_5_1338.6.jpg`

### seg_setup_deficit · deficit_scoreboard_anchor
- 窗口 `1409.430`–`1412.930` · anchor=None · complete=None
- checklist: `{"goal_inside_window": null, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=1410.43 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_setup_deficit_in_plus_1_1410.4.jpg`
- [OK] t=1411.18 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_setup_deficit_mid_1411.2.jpg`
- [OK] t=1411.93 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_setup_deficit_out_minus_1_1411.9.jpg`

### seg_equalizer_goal_action · equalizer_goal_action
- 窗口 `6437.644`–`6459.644` · anchor=6449.644 · complete=True
- checklist: `{"goal_inside_window": true, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=6438.64 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_equalizer_goal_action_in_plus_1_6438.6.jpg`
- [OK] t=6448.64 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_equalizer_goal_action_mid_6448.6.jpg`
- [OK] t=6458.64 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_equalizer_goal_action_out_minus_1_6458.6.jpg`
- [OK] t=6449.64 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_equalizer_goal_action_anchor_6449.6.jpg`
- [OK] t=6451.14 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_equalizer_goal_action_anchor_plus_1_5_6451.1.jpg`

### seg_go_ahead_goal_action · go_ahead_goal_action
- 窗口 `6831.088`–`6853.088` · anchor=6843.088 · complete=True
- checklist: `{"goal_inside_window": true, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=6832.09 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_go_ahead_goal_action_in_plus_1_6832.1.jpg`
- [OK] t=6842.09 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_go_ahead_goal_action_mid_6842.1.jpg`
- [OK] t=6852.09 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_go_ahead_goal_action_out_minus_1_6852.1.jpg`
- [OK] t=6843.09 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_go_ahead_goal_action_anchor_6843.1.jpg`
- [OK] t=6844.59 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_go_ahead_goal_action_anchor_plus_1_5_6844.6.jpg`

### seg_ending_final_scoreboard · ending_final_scoreboard
- 窗口 `6956.120`–`6959.620` · anchor=None · complete=None
- checklist: `{"goal_inside_window": null, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=6957.12 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_ending_final_scoreboard_in_plus_1_6957.1.jpg`
- [OK] t=6957.87 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_ending_final_scoreboard_mid_6957.9.jpg`
- [OK] t=6958.62 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/uae_oman/qc_pack/frames/seg_ending_final_scoreboard_out_minus_1_6958.6.jpg`

