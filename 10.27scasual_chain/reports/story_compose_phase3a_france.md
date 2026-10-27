# T01 Story Plan — 2022年11月23日 法国vs澳大利亚
- tier: `story` · template: `T01_comeback`
- verification: `partial`
- protagonist: {'side': 'left', 'team_name': '法国', 'teams': {'left': '法国', 'right': '澳大利亚'}}

## Summary
法国 逆风翻盘候选剪辑方案（规则基线）：落后→蓄力→扳平→反超→收尾。

## 铺垫
主角落后比分 0:1（score_path 规则事实）。 叙事补充回放（非真实比赛主时序）。
- `seg_setup_deficit` · shot=live · time=score_path_only · in=1531.65 out=1543.65 · events=['event_000027'] · frames=[]
  - 主角落后比分 0:1（score_path 规则事实）。
- `seg_setup_replay_supp` · shot=replay_supplement · time=event_ms · in=2446.817 out=2458.817 · events=['event_000027'] · frames=[]
  - 叙事补充回放（非真实比赛主时序）。

## 蓄力
蓄力动作 角球（live）。 蓄力动作 射门（live）。
- `seg_buildup_event_000031` · shot=live · time=event_ms · in=1585.9 out=1597.9 · events=['event_000031'] · frames=[]
  - 蓄力动作 角球（live）。
- `seg_buildup_event_000072` · shot=live · time=event_ms · in=2107.89 out=2119.89 · events=['event_000072'] · frames=[]
  - 蓄力动作 射门（live）。

## 转折
扳平至 1:1（score_path）。
- `seg_equalizer` · shot=live · time=pending_review · in=2509.29 out=2521.29 · events=['event_000082'] · frames=[]
  - 扳平至 1:1（score_path）。

## 高潮
反超至 2:1（score_path）。
- `seg_go_ahead` · shot=live · time=pending_review · in=2900.31 out=2912.31 · events=['event_000091'] · frames=[]
  - 反超至 2:1（score_path）。

## 收尾
收尾/终场。
- `seg_ending` · shot=live · time=event_ms · in=7237.8 out=7249.8 · events=['event_000302'] · frames=[]
  - 收尾/终场。

## Missing evidence
- setup_visual_mock_only_not_factual
- verify_equalizer_goal_action_mock_only
- equalizer_goal_event_missing:event_000082
- verify_go_ahead_goal_action_mock_only
- go_ahead_goal_event_missing:event_000091
- climax_event_missing:event_000260
- climax_event_missing:event_000264
- post_climax_reaction_mock_only

## EDL (include_in_cut)
- #1 铺垫 [1531.65, 1543.65] live events=['event_000027']
- #2 铺垫 [2446.817, 2458.817] replay_supplement events=['event_000027']
- #3 蓄力 [1585.9, 1597.9] live events=['event_000031']
- #4 蓄力 [2107.89, 2119.89] live events=['event_000072']
- #7 收尾 [7237.8, 7249.8] live events=['event_000302']
