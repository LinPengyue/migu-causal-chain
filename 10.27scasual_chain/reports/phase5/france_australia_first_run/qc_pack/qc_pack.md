# QC 证据包：france_australia_first_run

> 自动抽帧仅供人工审片。**不构成**语义核验通过。`render_ready` 仍为 false。

## 检查项说明
- 进球锚点是否落在裁剪窗口内
- 是否误用比分牌/回放充当进球直播（需看图）
- 是否保留进攻上下文（需看图）
- 花屏避让是否破坏进球完整性（见 goal_action_complete）
- Summary / Graph / EDL / 视频一致性（对照同目录产物）

### seg_setup_deficit · deficit_scoreboard_anchor
- 窗口 `1534.650`–`1538.150` · anchor=None · complete=None
- checklist: `{"goal_inside_window": null, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=1535.65 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_setup_deficit_in_plus_1_1535.7.jpg`
- [OK] t=1536.40 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_setup_deficit_mid_1536.4.jpg`
- [OK] t=1537.15 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_setup_deficit_out_minus_1_1537.2.jpg`

### seg_equalizer_goal_action · equalizer_goal_action
- 窗口 `2398.091`–`2420.091` · anchor=2410.091 · complete=True
- checklist: `{"goal_inside_window": true, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=2399.09 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_equalizer_goal_action_in_plus_1_2399.1.jpg`
- [OK] t=2409.09 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_equalizer_goal_action_mid_2409.1.jpg`
- [OK] t=2419.09 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_equalizer_goal_action_out_minus_1_2419.1.jpg`
- [OK] t=2410.09 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_equalizer_goal_action_anchor_2410.1.jpg`
- [OK] t=2411.59 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_equalizer_goal_action_anchor_plus_1_5_2411.6.jpg`

### seg_go_ahead_goal_action · go_ahead_goal_action
- 窗口 `2714.188`–`2736.188` · anchor=2726.188 · complete=True
- checklist: `{"goal_inside_window": true, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=2715.19 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_go_ahead_goal_action_in_plus_1_2715.2.jpg`
- [OK] t=2725.19 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_go_ahead_goal_action_mid_2725.2.jpg`
- [OK] t=2735.19 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_go_ahead_goal_action_out_minus_1_2735.2.jpg`
- [OK] t=2726.19 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_go_ahead_goal_action_anchor_2726.2.jpg`
- [OK] t=2727.69 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_go_ahead_goal_action_anchor_plus_1_5_2727.7.jpg`

### seg_lead_extend_1_goal_action · lead_extend_1_goal_action
- 窗口 `5422.743`–`5444.743` · anchor=5434.743 · complete=True
- checklist: `{"goal_inside_window": true, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=5423.74 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_lead_extend_1_goal_action_in_plus_1_5423.7.jpg`
- [OK] t=5433.74 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_lead_extend_1_goal_action_mid_5433.7.jpg`
- [OK] t=5443.74 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_lead_extend_1_goal_action_out_minus_1_5443.7.jpg`
- [OK] t=5434.74 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_lead_extend_1_goal_action_anchor_5434.7.jpg`
- [OK] t=5436.24 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_lead_extend_1_goal_action_anchor_plus_1_5_5436.2.jpg`

### seg_lead_extend_1_scoreboard · lead_extend_1_scoreboard_anchor
- 窗口 `5593.300`–`5596.800` · anchor=None · complete=None
- checklist: `{"goal_inside_window": null, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=5594.30 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_lead_extend_1_scoreboard_in_plus_1_5594.3.jpg`
- [OK] t=5595.05 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_lead_extend_1_scoreboard_mid_5595.1.jpg`
- [OK] t=5595.80 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_lead_extend_1_scoreboard_out_minus_1_5595.8.jpg`

### seg_lead_extend_2_goal_action · lead_extend_2_goal_action
- 窗口 `5650.164`–`5672.164` · anchor=5662.164 · complete=True
- checklist: `{"goal_inside_window": true, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=5651.16 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_lead_extend_2_goal_action_in_plus_1_5651.2.jpg`
- [OK] t=5661.16 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_lead_extend_2_goal_action_mid_5661.2.jpg`
- [OK] t=5671.16 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_lead_extend_2_goal_action_out_minus_1_5671.2.jpg`
- [OK] t=5662.16 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_lead_extend_2_goal_action_anchor_5662.2.jpg`
- [OK] t=5663.66 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_lead_extend_2_goal_action_anchor_plus_1_5_5663.7.jpg`

### seg_lead_extend_2_scoreboard · lead_extend_2_scoreboard_anchor
- 窗口 `5819.460`–`5822.960` · anchor=None · complete=None
- checklist: `{"goal_inside_window": null, "not_scoreboard_as_goal": true, "glitch_demotion": true, "semantic_verified": false, "human_review_required": true}`
- integrity: `None`
- [OK] t=5820.46 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_lead_extend_2_scoreboard_in_plus_1_5820.5.jpg`
- [OK] t=5821.21 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_lead_extend_2_scoreboard_mid_5821.2.jpg`
- [OK] t=5821.96 → `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/france_australia_first_run/qc_pack/frames/seg_lead_extend_2_scoreboard_out_minus_1_5822.0.jpg`

