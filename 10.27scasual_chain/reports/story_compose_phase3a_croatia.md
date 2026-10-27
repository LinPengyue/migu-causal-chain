# T01 Story Plan — 2022-11-28 克罗地亚vs加拿大
- tier: `candidate` · template: `T01_comeback`
- verification: `partial`
- protagonist: {'side': 'left', 'team_name': '克罗地亚', 'teams': {'left': '克罗地亚', 'right': '加拿大'}}

## Summary
克罗地亚 翻盘候选不完整方案；缺口见 missing_evidence。

## 铺垫
主角落后比分 0:1（score_path 规则事实）。
- `seg_setup_deficit` · shot=live · time=score_path_only · in=1075.06 out=1087.06 · events=['event_000004'] · frames=[]
  - 主角落后比分 0:1（score_path 规则事实）。

## 蓄力


## 转折
扳平至 1:1（score_path）。
- `seg_equalizer` · shot=live · time=pending_review · in=3141.98 out=3153.98 · events=['event_000068'] · frames=[]
  - 扳平至 1:1（score_path）。

## 高潮
反超至 2:1（score_path）。
- `seg_go_ahead` · shot=live · time=score_path_only · in=3693.35 out=3705.35 · events=['event_000076'] · frames=[]
  - 反超至 2:1（score_path）。

## 收尾
收尾/终场。
- `seg_ending` · shot=live · time=event_ms · in=7942.16 out=7954.16 · events=['event_000159'] · frames=[]
  - 收尾/终场。

## Missing evidence
- setup_visual_mock_only_not_factual
- missing_live_buildup
- verify_equalizer_goal_action_mock_only
- equalizer_goal_event_missing:event_000068
- verify_go_ahead_goal_action_mock_only
- post_climax_reaction_mock_only

## EDL (include_in_cut)
- #1 铺垫 [1075.06, 1087.06] live events=['event_000004']
- #3 高潮 [3693.35, 3705.35] live events=['event_000076']
- #4 收尾 [7942.16, 7954.16] live events=['event_000159']
