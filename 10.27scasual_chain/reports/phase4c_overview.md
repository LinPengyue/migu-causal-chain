# Phase 4C 总览 — 关键进球定位与完整翻盘故事准备

基准: `story-va-phase2c` @ `88e047d` → 本提交  
**无付费 API** · Video-RSI Thinking 关闭配置保留但不重复实验 · **`render_ready=false`**

## 交付清单

1. `phase4c_equalizer_localization.md` / `.json` — 扳平精细定位  
2. `phase4c_go_ahead_localization.md` / `.json` — 反超候选定位  
3. `phase4c_t01_evidence_table.md` / `.json` — 五段完整性  
4. `phase4c_croatia_plan.json` + `phase4c_croatia_candidate_edl.json` + 本地 preview（未提交 mp4）  
5. `phase4c_seed_generalization.md` / `.json` + `seed_targets_from_story` 代码与测试  

## 关键数字

| 进球 | 入网 media_sec（候选） | 记分牌锚点 | 旧搜索窗是否命中 |
|------|------------------------|------------|------------------|
| 扳平 | **~3067** | 3145.98 | 是（seed 3065.9） |
| 反超 | **~3525** | 3697.35 | **否**（旧窗起 3617） |

停止：不启动下一轮付费实验。
