# Phase 4C — 跨比赛通用化改造建议

## 现状问题

`croatia_seed_targets()` 硬编码：

- equalizer live ≈3065.903  
- go_ahead board ≈3697.35，搜索窗仅 **board−80 → board−5**

本场反超 live ≈**3525**，Δ(board)≈**−172s**，落在旧窗外 → 无法泛化到任意比赛。

## 已落地（无计费）

新增 `seed_targets_from_story(story, causal=None)`：

1. 用 `_comeback_score_steps` 取扳平/反超 **记分牌**锚点  
2. 优先 `story.events` / `causal_chains` 的 **live Goal** 作 `seed_center`  
3. 剔除与 board 相差 <1s 的伪动作（如本场 3697「射门」）  
4. 无候选时 `board − 40` fallback，并把 go_ahead 粗搜默认扩到 **~200s**  
5. `select_seed_targets(..., story=, causal=, prefer_story=True)` 可选启用  
6. 保留 `croatia_seed_targets()` 仅作兼容基线，注释标明过窄风险  

测试：`test_phase4c_seed_from_story.py`（5 项通过，无 HTTP）。

## 后续改造建议（不在本阶段做付费实验）

1. Phase4 CLI / `run_phase4a` 默认读 story+causal 调 `seed_targets_from_story`  
2. locate 分层：粗步长 3s → 细 0.5s（本阶段手工流程可脚本化）  
3. delivery `Score_Recognition` 翻转区间辅助缩窗，但仍需画面确认  
4. 严禁 board 时间写入 `equalizer_goal_action` / `go_ahead_goal_action` 的 media 窗  
5. 其他比赛真实 VLM **需单独授权**，本阶段停止  

## 本场 story-driven seed 结果

- equalizer: story Goal @3065.903（verify）  
- go_ahead: causal Goal @3523.574（locate；画面入网≈3525）
