# France vs Australia — 首次零修改运行记录

**算法冻结点：** Phase 5.1c（结尾去重 + 弧前背景规划）合入后、对本场零修改。  
**视频：** `/mnt/data4/migu/2022年11月23日 法国vs澳大利亚.mp4`  
**标注：** `data/交付_out/2022年11月23日 法国vs澳大利亚{,_causal}.json`  
**输出：** `_local_render/phase5/france_australia_first_run/` · 预览 `france_australia_story_{clean,qc}.mp4`

## 第一次运行摘要（未针对性调参）

| 项 | 结果 |
|----|------|
| T01 tier | `story` |
| 主角 | left 法国 |
| 成片时长 | ~136s |
| 背景规划 | mode=`none`（弧前仅 0:0） |
| 收束 | `title_card_only`（无重复比分牌） |
| 开场失球 live | **缺失** → `missing_live_goal_action:opponent_opening`（仅有落后记分牌） |
| 扳平/反超/扩大 | EDL 含 equalizer / go_ahead / lead_extend_1 / lead_extend_2 动作候选 |
| match_end | 拒绝（距终场比分 Δ≈1421s，超出候选视界） |
| render_ready | false |
| 语义核验 | 未做（规则级 `goal_action_complete` ≠ 视觉语义通过） |

本目录保存**首次**完整产物；后续若改算法再跑不得覆盖本笔记所指向的 first-run 语义（可另开目录）。
