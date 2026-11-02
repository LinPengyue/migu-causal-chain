# V3-P3 First-Live Localization Report

**Branch:** `story-va-v3-plan2`  
**Baseline:** `6ff79f7`  
**Worktree:** `/data2/lpy1/worktrees/migu-story-va-v3-plan2`  
**Focus case:** B `opening_deficit` — Osasuna **1:1 → 2:1**  
**Outputs:** `/data2/lpy1/_story_va_outputs/v3/plan2/p3_b_opening_localize/`  
**render_ready:** `false` (always)

---

## Headline verdict

**B 的 2:1 首次 LIVE 动作：定位到了可信候选窗口，但未达到 `verified_first_live` / Gate 通过。**

| 问题 | 结论 |
|------|------|
| 是否成功定位首次 LIVE 动作？ | **部分成功**：连续精确裁剪窗口 **3132–3146s** 覆盖角球→门前混战→奥萨苏纳庆祝→记分牌 1:1→2:1；语义标签 `possible_first_live` |
| 是否 Gate / `agent_auto_verified`？ | **否**。`n_goal_action_verified_ok=0`，`n_agent_auto_verified=0` |
| 主失败模式 | **视频语义理解不足**（无可用本地免费 VLM；宽角度 LIVE 无法自动认证球过线；清晰入网只在记分牌已是 2:1 的后续视角） |
| 次要信号问题 | **原始事件稀疏**（3120–3199 几乎无 Shot/Corner）；**记分牌 OCR 对竖排 scorebug 失效**；事件比分确认 **3199.66** 远晚于真实动作与板面更新 |

验收桶：`possible_clip_semantic_insufficient_for_auto_verify`  
（找到可能进球片段 + 连续视频证据，但语义不足以自动验证）

未降低 V2/V3 Gate；未自动成片。

---

## 1. P2 补证缺口 → P3 能力

旧 `targeted_evidence.py` 只做历史窗/确认前块裁剪 + 一律 `unresolved`，不区分：

- 候选片段提取成功 vs 进球动作验证成功  
- LIVE 射门/入网 vs 庆祝 vs 回放 vs 错误进攻方

P3 新增：

| 模块 | 作用 |
|------|------|
| `first_live_localize.py` | 比分边界、未覆盖区间优先候选、语义标签、精确解码裁剪 |
| `localize_cli.py` | 单角色/多角色定位 CLI（零付费 API） |
| `targeted_evidence.run_p3_localization_pass` | 与 P2 打包路径并存的定位入口 |
| `test_first_live_localize.py` | 边界合并、未覆盖优先、禁止无语义日志冒充 verified |

语义标签集合：`pre_goal_only` | `shot_only` | `post_goal_celebration` | `replay` | `wrong_attacking_side` | `possible_first_live` | `verified_first_live` | `unresolved`。

**硬约束：** 无可靠本地视频语义模型时，**禁止**用规则推断写成 `agent_auto_verified` / `automated_video_verified`。人工复核记为独立 `human_video_review_record`。

通用排序**不**硬编码 B 的 PTS；历史/人工比分观察仅作本次运行的输入线索。

---

## 2. 真实视频时间线（B opening）

源视频：`/mnt/data4/migu/10月27日 25-26赛季西甲第10轮 奥萨苏纳VS塞尔塔 国语.mp4`  
事件确认：`event_000456` Score `[2,1]` @ **3199.66** LIVE（中场推进，**不是**进球动作）。

### 2.1 比分边界（人工读帧；OCR 失败）

| PTS (约) | 板面 | 画面 |
|----------|------|------|
| 3130 | **1–1** | LIVE 角球 |
| 3132–3135.5 | **1–1**（滞后） | LIVE 门前混战；GK 扑救；#22 举手 |
| 3140 | **1–1** | 边线反应；**最后清晰旧分** |
| 3144 | **2–1** | 庆祝；**首次清晰新分** |
| 3152+ | 2–1 | 庆祝 / GOO(L) 条 |
| **3175** | **已是 2–1** | 球门后视角**球入网清晰** → **回放风险**（不能当 first-live） |
| 3199.66 | 2–1 | 事件确认，中场 LIVE |

未知区间（旧分最后观察 → 新分首次观察）：**3140 → 3144**（板面滞后带）。  
真实动作落在板面仍为 1:1 的 **~3133–3136**，由 `score_unknown_core` 向前扩展 8s 覆盖到 **3132–3146**。

### 2.2 为何不再只剪 3130–3135

历史 G2.2 窗 3128–3153 已被覆盖；P3 优先：

1. `score_unknown_core`（由比分边界推导，非写死 PTS）  
2. 历史未覆盖 gap（本场约 3089–3114 → `pre_goal_only`）  
3. 历史线索仅作低优先级复核  

本次 top1 **不是**“再次导出同一 historical_clue”，而是比分边界驱动的 `opening_deficit_score_unknown_core_3132`。

---

## 3. 定位运行结果

命令要点：`localize_cli --role opening_deficit --skip-ocr` + 人工比分观察/复核输入  
产物：`p3_b_opening_localize/run/`、`gate/`

| candidate_id | 窗 | 标签 | 提取 | 验证 |
|--------------|----|------|------|------|
| `opening_deficit_score_unknown_core_3132` | 3132–3146 | **possible_first_live** | OK（accurate H.264） | 否 |
| `opening_deficit_uncovered_gap_tail_3089` | 3089.76–3114.76 | **pre_goal_only** | OK | 否 |

连续片段：

`.../clips/opening_deficit_score_unknown_core_3132_continuous_accurate.mp4`  
（hybrid seek + libx264，非 stream-copy）

人工复核记录（独立证据类型，**非** auto-verify）：

- `observed_shot=true`（门前攻防 / 射门向）  
- `observed_net=false`（LIVE 广角无法认证过线）  
- `attacking_team_match=true`（红衣奥萨苏纳庆祝 ↔ 主队 1→2）  
- 清晰入网仅见于 ~3175 且板面已是 2:1 → **replay / net_seen_only_in_replay 风险**

Gate（未放宽）：

```text
opening_deficit: ok=false reason=incomplete_shot_net_team_first_live
all_critical_video_verified=false
render_ready=false
```

---

## 4. 失败模式归因（按优先级）

1. **视频语义理解不足（主因）**  
   - ollama 无可用视觉模型；禁止付费 API  
   - Tesseract 对 LaLiga 竖排比分基本读不出  
   - 规则/人工可标 `possible_first_live`，不能伪造 `automated_video_verified`

2. **信号缺失（事件）**  
   - 3120–3199 事件几乎为空；无 LIVE Shot 可锚定  
   - 3199.66 确认是比分状态事件，延迟大

3. **时间轴 / 板面滞后（已知、已处理）**  
   - 动作 ~3134，板面 3144，事件 3199  
   - 系统用边界约束检索，**不用确认秒当 goal_action_sec**

4. **源视频质量**  
   - LIVE 主镜头可用；入网细节需靠后视角，但该视角出现时比分已更新 → 质量足够看动作，不足以从单角度自动证网

5. **候选检索**  
   - **未失败**：未覆盖优先 + 比分未知核找到了正确 LIVE 带

---

## 5. 与验收三档对照

| 档位 | 是否命中 |
|------|----------|
| 找到首次直播动作且有充分连续证据 → verified | **否**（连续证据有，网口认证不足） |
| 找到可能进球片段，语义不足 | **是** ← 本报告 |
| 预算内未找到 | 否 |

扩展策略：通用机制已落地；**在出现可靠本地语义模型或正式 `verified_first_live` 人工结论之前，不批量扩展 A/B 其余五球**（避免再次“只打包 unresolved”）。

---

## 6. 测试

```text
python -m unittest story_video_agent_v3.test_first_live_localize story_video_agent_v3.test_pipeline
→ 14 tests OK
```

---

## 7. 冻结与产物边界

- V1 / V2 / 8.31 / run02 / run03：**未改写**  
- 新代码仅 `story_video_agent_v3/*` + 本报告  
- 新媒体证据仅写入 `_story_va_outputs/v3/plan2/p3_b_opening_localize/`  
- `render_ready=false` 全程保持
