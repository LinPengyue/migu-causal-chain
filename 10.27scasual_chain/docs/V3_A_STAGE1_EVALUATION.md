# V3-A Stage-1 Evaluation（真实数据结构审计）

**开发分支：** `story-va-v3-a`  
**冻结基线：** `story-va-v3-r-frozen-20261103` → `2d1ec9c`  
**付费 API：** 0  
**render_ready / 正式交付授权：** false / **NOT_AUTHORIZED**（全场）  
**说明：** 结构代理分 ≠ 视觉确认质量分；无法自动判断项标 **UNKNOWN**。

---

## 1. 测试执行结果

命令：

```bash
PYTHONPATH=10.27scasual_chain/algo \
python -m unittest discover \
  -s 10.27scasual_chain/tests \
  -p 'test_v3a_quality_audit.py' -v
```

| 结果 | 值 |
|------|----|
| 通过 | **10 / 10** |
| 失败 | 0 |
| 修复 | 本轮无需改码（HEAD 已含 trailing-freeze / fail-closed 相关提交） |

覆盖用例：`structural_proxy` 永不授权成片、缺对方进球不可用记分牌顶替、不完整/回放/坏窗/顺序倒置/重复事件映射、已知损坏硬错误、缺 scope→UNKNOWN、片尾 freeze 保留。

---

## 2. 四场审计输入（V3-R 冻结产物，未重渲）

| 场 | phase5 目录 | `v3a_quality_audit.json` |
|----|-------------|---------------------------|
| A 阿联酋—阿曼 | `.../closed_loop_A_uae_oman/04_phase5_p1_polish/` | 同目录 |
| B 奥萨苏纳—塞尔塔 | `.../closed_loop_B_osasuna_celta/04_phase5_p1_polish/` | 同目录 |
| C 克罗地亚—加拿大 | `.../closed_loop_C_croatia_canada/04_phase5/` | 同目录 |
| FR 法国—澳大利亚 | `.../closed_loop_FR_france_australia_zeroshot/04_phase5/` | 同目录 |

约束遵守：未改原始 EDL / 比赛输入 / 未重渲基线 MP4；仅只读审计并写入 audit JSON。

---

## 3. 自动审计结果摘要

| 场 | coverage | coherence | image (decode proxy) | structural_proxy_pass | P0 | P1 | P2 |
|----|----------|-----------|----------------------|-----------------------|----|----|-----|
| A | 100.0 | 100.0 | SCREENED score=100（freeze×2） | **true** | 0 | 0 | 1 title freeze |
| B | 100.0 | 100.0 | SCREENED score=100（freeze×3） | **true** | 0 | 0 | 1 title freeze |
| C | 100.0 | 100.0 | SCREENED score=100（freeze×2） | **true** | 0 | 0 | 1 title freeze |
| FR | **66.7** | 100.0 | SCREENED score=100（freeze×2） | **false** | **1 missing opponent_opening** | 0 | 1 title freeze |

共同：`release_decision=NOT_AUTHORIZED`，`render_ready=false`，`unverified=[live_vs_replay_visual_truth, VLM_semantics, shot_event_grounding]`。

image 分仅为 **decode_error_proxy_only**；片头/片尾 freeze 多与标题卡一致，**不得**当作严重画面损坏。

---

## 4. 人工对照（Verifier vs 视觉/叙事）

### 4.1 关键故事元素 / 对方进球

| 场 | 自动判断 | 人工 | Verifier |
|----|----------|------|----------|
| A | 三关键 goal_action 在 EDL | 1337/6449/6843 LIVE 破门此前 QC **PASS** | 覆盖代理 **正确（未视觉签发）** |
| B | 弧内三球在 EDL | 3133/5657/6791 LIVE **PASS**；全场首球 **1979** 仅背景板 | 对 **T01 selected_arc** 正确；全场首球不在硬要求 → 产品若要全集则属 **漏报风险 / UNKNOWN 产品定义** |
| C | 三关键+扩大在 EDL | 开场/扳平/反超 LIVE 大体 **PASS**；原子 Goal@2451 噪声未进 EDL | 覆盖代理大体正确；噪声原子 **UNKNOWN→人工确认未误用** |
| FR | **缺 opponent_opening** | 仅有 0:1 记分牌；可用 Goal@1351 视觉 **FAIL**（非破门） | **P0 正确命中漏检** |

### 4.2 回放 / 重复 / 错误时间窗

| 场 | 自动 | 人工 |
|----|------|------|
| A/B/C/FR | 无 `replay_as_primary` / `duplicated_goal_event` / `bad_media_window` | EDL `is_replay=false`；B 重复蓄力已在 V3-R Pass3 去掉；FR 错误原子未进 opening 窗 |
| 视觉 LIVE 真伪 | **未测**（`unverified`） | 依赖既有抽帧 QC；本轮未重抽 → 记 **UNKNOWN（本审计未复验每一帧）**，引用既有 QC 报告为旁证 |

### 4.3 叙事节拍 / 衔接

| 场 | 自动 beat 顺序 | 人工 |
|----|----------------|------|
| 全场 | coherence 100，无 inversion | 铺垫→蓄力→转折→高潮基本完整；A/C 蓄力偏弱；B 角色名「开场失球」实为弧内失球易误解 → **P1 叙事命名/衔接** |
| FR | 缺铺垫失球动作 → 从记分牌直接到扳平 | **不自然**；与 P0 同源 |

### 4.4 严重画面损坏

| 场 | 自动 | 人工 |
|----|------|------|
| 全场 | decode_error_count=0 | 未见严重花屏/解码失败证据；标题卡 freeze = **预期** |
| P2 freeze 告警 | 四场皆有 | **误报倾向（相对“损坏”语义）**：应视为需人工确认的 title-card，而非 P0 |

### 4.5 Verifier 正误汇总

| 类型 | 项 |
|------|-----|
| **正确** | FR 缺对方进球动作 P0；结构分不授权成片；空 visual → unverified；标题 freeze 仅 P2 |
| **误报（相对损坏）** | 四场 `possible_image_anomaly` 把片头/片尾标题卡 freeze 标成异常——**正确作为警告，错误若解读为损坏** |
| **漏报 / 能力外** | LIVE/REPLAY 视觉真伪；FR 错误 Goal 原子质量；C 原子噪声；B 全场首球是否应入片（超 selected_arc）；弱蓄力叙事 |
| **尚未核验 UNKNOWN** | 本轮未对四场 MP4 重新逐球抽帧；依赖历史 QC；VLM 语义全无 |

---

## 5. P0 / P1 / P2 问题清单

### P0
1. **FR：缺少 `opponent_opening_goal_action`**（自动+人工一致）。Planner 须定位真实澳队首球 LIVE，禁止用记分牌顶替，禁止使用已证伪的 @1351 原子。

### P1
1. **B：弧内「opponent_opening」命名/观众理解** — 易当成全场第一球；Planner 应区分 arc_deficit_goal vs match_opening_goal 或补背景说明。  
2. **A/C：蓄力段弱或对手定位球被丢弃后叙事偏空** — 可选补主角进攻蓄力，避免失球板后长时间跳到扳平。  
3. **C：8.31 outcome 覆盖弱 + 噪声 Goal 原子** — Planner/上游需防错误原子进入动作窗（本场未进关键窗，但属系统风险）。

### P2
1. 四场片头/片尾 freeze 告警（多半标题卡）— 人工确认即可，勿当解码损坏。  
2. carrier_event unresolved / ending_match_end 拒绝等 `missing_evidence` — 已知候选交付噪声，不升 P0 除非影响关键球。

---

## 6. 各场 Planner 最值得修的三个问题

### A
1. 保持三球 LIVE 窗，补强或明确「弱蓄力」策略（避免无关角球回流）。  
2. 对 opening/eq/ga 做一次可追溯的视觉确认门闩（当前仅结构代理）。  
3. 收敛 `*_carrier_unresolved` 对交付摘要的噪音。

### B
1. 澄清弧起点失球 vs 全场首球（1979）是否进片的产品规则。  
2. 叠字/包装远离记分牌（历史分钟误读已在 P1 polish 缓解，需防回归）。  
3. 视觉签发三关键球（结构已齐）。

### C
1. 过滤/校验噪声 Goal 原子（如 @2451）。  
2. 提升 8.31→故事对 LIVE Goal 的一致覆盖。  
3. 弱蓄力与扩大球窗的人工/自动复验。

### FR
1. **恢复真实对方首球 LIVE 动作**（P0）。  
2. 拉黑错误 Goal@1351 类候选。  
3. 复验扳平/反超/扩大窗并写入可审计证据（仍不宣称 render_ready）。

---

## 7. 第一阶段是否可进入 Planner 集成

**可以进入 Planner 集成开发（有条件）。**

依据：
- Stage-1 单元测试 **全绿**；审计工具对冻结四场可复跑。  
- 已得到可操作的 **FR P0** 与跨场 P1/P2 清单。  
- A/B/C 结构代理通过，但 **一律未授权**；Planner 第一刀应优先 FR 对方进球修复与「结构通过 ≠ 视觉通过」的证据接口。

**不可宣称：** 任一候选 MP4 已正式交付 / `render_ready=true` / 视觉语义已核验。

---

## 8. 产物路径

- 本报告：`10.27scasual_chain/docs/V3_A_STAGE1_EVALUATION.md`  
- 审计 JSON：上述四场 `04_phase5*/v3a_quality_audit.json`  
- 基线 SHA：`2d1ec9c`（`story-va-v3-r-frozen-20261103`）
