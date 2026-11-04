# V3-A 冻结版本跨比赛三轮真实评测（A/B/C）

**性质：** 仅评测，**未修改** Planner / VLM / EDL Revision / Verifier / 阈值 / 门禁 / 故事模板。  
**分支：** `story-va-v3-a`  
**实验代码 SHA：** `2fc6b165f4b2b84a115d296689d3e061d6ff9ece`  
**文档 HEAD（评测时工作区）：** `8ad2baf430f0ef8ea82067e62992c1f0fc78b75d`  
**工作区：** 干净；`2fc6b16..HEAD` 仅含既有法国场评估文档。  
**配置（统一）：** 真实 API · `max_rounds=3` · `max_calls=24` · `max_cost_usd=0.30`/场 · `quality_threshold=75` · `--no-stop-on-quality-threshold` · `max_completion-tokens=2048`  
**输入：** 各场 `04_phase5`（V3-R）+ `predicted_causal_live_goals_only.json` + 原始视频 + `v3a_stage2_planner_proposal.json`  
**冻结校验：** A/B/C phase5 `candidate_edl/story_plan/t01_story` SHA256 评测前后一致。

META：`/data2/lpy1/_story_va_outputs/v3/plan2/v3a_cross_match_3round_20261104_META/`

---

## 汇总表（先看结论）

| 场次 | 真实编排跑满 3 轮 | Agent 产生有效修订 | 可观察成片质量改善（相对 V3-R） | 正式交付条件 |
|------|-------------------|--------------------|----------------------------------|--------------|
| **A 阿联酋vs阿曼** | **是**（完整 multimodal） | **是**（R1 接受证据绑定） | **存疑/未宣称**：时长↑但引入重复 opening；go-ahead 被标 `SUSPECTED_REPLAY`；API 100 分不作质量证明 | **否**（`release_eligible=false`，多段 `NOT_VERIFIED`） |
| **B 奥萨苏纳vs塞尔塔** | **编排完成但 multimodal 失败**（见下） | **官方重跑：否** | **官方重跑：无**（EDL=基线） | **否**（结构门可过，但 `release_decision=NOT_AUTHORIZED`；无产品授权） |
| **C 克罗地亚vs加拿大** | **编排完成但 Planner 全超时** | **否** | **无**（EDL=基线） | **否**（同上） |

**说明（B）：** 首次运行在 R1 真实修订后于 R2 触发 `FrameBudgetExhausted` 中断；按要求整场重跑后，Planner API 连续超时 → `rule_fallback`，无 VLM/无修订。下文同时记录首次部分产物与官方重跑。

**费用合计（估算）：** A `0.0439` + B 首次部分 `≈0.0215` + B 重跑 `0.0031` + C `0.0032` ≈ **$0.072** ≪ $0.90。

---

## 场次 A：阿联酋 vs 阿曼

**输出：** `/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/v3a_cross_match_3round_20261104`  
**调用：** 18 · tokens 173437 · est **$0.0439** · `real_ok=18`  
**轮次：** 3/3 · `best_round=1` · `accepted_revision=true` · `release_decision=NOT_AUTHORIZED`

### 逐轮

| 轮 | prior 反馈 | Planner/VLM | 主要发现 | EDL 变化 | 接受 |
|----|------------|-------------|----------|----------|------|
| R1 | 无 | real / real | 多段 live 风险；补/替换 opening、equalizer、go-ahead | 证据绑定：opening 扩窗 + **重复** `…_live` 同行；eq/ga 扩窗 | **接受** `quality_improvement` |
| R2 | **是** | real / real | 重复 opening；live 未核验；buildup/title 未证 | 多为 `mark_unresolved`/`keep`；drop 未形成证据绑定写盘 | **拒绝** `api_verifier_degraded…` + `no_evidence_bound…` |
| R3 | **是** | real / real | 重复段、buildup 疑似回放剪辑、go-ahead 混合观察、title 锚错赛 | 无证据绑定修订 | **拒绝** 同上 |

### 四维评分（UNKNOWN 不计入均值）

| 轮 | coverage | coherence | image | live_authenticity | composite | UNKNOWN |
|----|----------|-----------|-------|-------------------|-----------|---------|
| R1 | 100 api | 100 api | null | **40** api | **80.0**（3 维） | image |
| R2 | 100 rule_proxy | 100 rule_proxy | null | null | 100.0（2 维） | image, live |
| R3 | 100 rule_proxy | 100 rule_proxy | null | null | 100.0（2 维） | image, live |

R1 `live_segment_assessments` 要点：opening/eq `UNKNOWN`；**`seg_go_ahead_goal_action` = `SUSPECTED_REPLAY` score=30**。

### 相对 V3-R

| | V3-R `04_phase5` | V3-A best |
|--|------------------|-----------|
| story_clean | ≈106.9s | ≈**160.9s** |
| EDL | 10 行 | 11 行：同 PTS 的 opening **双行**；eq/ga 窗口加宽 |

**人工对比关注：** 重复 opening 可能造成节奏拖沓；go-ahead 已有回放嫌疑；**不得**因镜头变多或 API 综合分当作成片变好。

**候选预览（非交付）：**  
`…/v3a_cross_match_3round_20261104/v3a_candidate_render/story_clean.mp4`  
`…/story_qc.mp4`

---

## 场次 B：奥萨苏纳 vs 塞尔塔

### B-1 首次运行（部分，已归档）

**路径：** `…/v3a_cross_match_3round_20261104_failed_FrameBudgetExhausted_partial/`  
**失败：** R2 VLM `FrameBudgetExhausted:no frame budget remaining for gap R2_tool_opponent_shot_pre`（冻结 Agent 行为；未改算法）。父进程 `set -e` 退出导致当时未开 C。

| 轮 | 状态 | 要点 |
|----|------|------|
| R1 | 完整并**接受** | `search_add` `go_ahead_post_goal_reaction_or_transition` 6775.88–6805.88（与 go-ahead 动作窗重叠）；composite **90**（live=70）；多段 `LIKELY_LIVE` |
| R2 | Planner 完成 → VLM **崩** | 诊断：buildup/反应重叠、叙事大空隙、opening 像庆祝、title 未核验；拟 drop/trim/多路 search_add |
| R3 | 未开始 | — |

部分费用估算 ≈ **$0.0215**（7 次计费调用痕迹）。部分候选预览曾渲 ≈146.98s（归档目录内）。

### B-2 官方重跑（当前主目录）

**输出：** `/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_B_osasuna_celta/v3a_cross_match_3round_20261104`  
**调用：** 15 记账 / HTTP≈12 · `real_ok=3` · `real_failures=9` · est **$0.0031**  
**原因：** Planner **9 次** `The read operation timed out` → 三轮皆 `planner_provider_mode=rule_fallback` · **无 VLM** · **无修订** · `best_round=0` · EDL **等于** V3-R。

| 轮 | prior 反馈 | 修订 | 四维 composite |
|----|------------|------|----------------|
| R1–R3 | R2/R3 有 prior 结构 | 空 intents | 100（仅 cov+coh api；image/live UNKNOWN） |

**候选预览：** 与 V3-R 同长 ≈**116.96s**  
`…/v3a_cross_match_3round_20261104/v3a_candidate_render/story_clean.mp4` · `story_qc.mp4`

**归因：** 重跑失败主因是 **Planner API 超时**，不是再一次 FrameBudget；首次部分结果证明该场在 API 正常时**能**产生 multimodal 修订，但被帧预算硬中断。

---

## 场次 C：克罗地亚 vs 加拿大

**输出：** `/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_C_croatia_canada/v3a_cross_match_3round_20261104`  
**调用：** 15 · `real_ok=3` · `real_failures=9` · est **$0.0032** · tokens 11866（几乎全是 Verifier）  
**现象：** 与 B 重跑同类——Planner 连续超时 → `rule_fallback` · 无 VLM · 无诊断/意图 · 无 EDL 变化 · `best_round=0` · `degraded_execution_success=true` · `multimodal_self_revision_success=false`

| 轮 | prior 反馈 | accept | composite |
|----|------------|--------|-----------|
| R1–R3 | R2/R3 消费 prior 壳 | 拒绝 `no_evidence_bound…` | 100（2 维）；image/live UNKNOWN |

**候选预览：** ≈**145.84s**（与 V3-R 相同时间线）  
`…/v3a_cross_match_3round_20261104/v3a_candidate_render/story_clean.mp4` · `story_qc.mp4`

**失败归因：** Planner API 超时导致无法进入真实自修订；**不是**输入缺失，也未放宽门禁。

---

## 费用与调用总览

| 场次 | 状态 | calls/HTTP | est_usd | 备注 |
|------|------|------------|---------|------|
| A | 完整 multimodal | 18 | 0.0439 | Planner/Vision/Verifier 均有 |
| B 首次 | R2 帧预算失败 | ≈7 计费痕迹 | ≈0.0215 | 已归档 |
| B 重跑 | Planner 超时 degraded | 15 / fail9 | 0.0031 | 主目录 |
| C | Planner 超时 degraded | 15 / fail9 | 0.0032 | — |
| **合计** | | | **≈0.072** | 预算 0.90 内 |

---

## 跨比赛适用性结论（不以单场代表全体）

1. **编排可移植性：** 三场均能用同一冻结入口读入各自 phase5/视频/因果链并写出独立 `out_dir`，phase5 指纹未改——**输入侧通用**成立。  
2. **真实自修订能力不稳定：** 仅 **A** 完整走通 Planner→VLM→Revision→Verifier；**B 首次**证明另一场也能改 EDL，但死于帧预算；**B 重跑与 C** 在相同配置下因 **Planner 超时** 退化为空转规则回退。跨场“成功 multimodal 自修订”**不能**从法国或 A 外推。  
3. **有效修订 ≠ 成片变好：** A 的接受修订带来重复镜头与回放嫌疑，API 高分/镜头变多**不**等于故事质量改善。  
4. **正式交付：** 无一场满足产品级正式交付；A 明确 `release_eligible=false`；B/C 结构门 `release_eligible=true` 但文案为仍需产品授权，且无 Agent 改善，**不得**当交付。  
5. **后续只记录、不改代码：** FrameBudgetExhausted、Planner 读超时、重复 role 绑定、SUSPECTED_REPLAY 未落盘修正——一律留待统一讨论。

### 最终四格再述

| 维度 | A | B（重跑主结果） | C |
|------|---|-----------------|---|
| 真实编排成功 | 是 | 流程完成 / multimodal 否 | 流程完成 / multimodal 否 |
| Agent 有效修订 | 是（R1） | 否（首次曾有，已中断） | 否 |
| 成片质量改善 | 未证实（有退行风险） | 无 | 无 |
| 正式交付 | 否 | 否 | 否 |

**总判：** 冻结 V3-A 在跨比赛上具备**跑通编排与独立产出**的通用外壳，但 **Agent 自修订的跨场可靠性与成片增益均未得到支持**；本评测暴露的是 API 超时、帧预算与修订副作用，而非某一场的特例调参失败。
