# V3-A Agent 法国场最小真实 API 实验

**分支：** `story-va-v3-a`  
**冻结基线：** `2d1ec9c`（未改）  
**模块：** `story_video_agent_v3.self_revise_agent`  
**主实验目录：**  
`/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_FR_france_australia_zeroshot/v3a_self_revise_fr_min_20261104_r3/`

## 预算与 Provider

| 项 | 值 |
|----|----|
| Planner | DeepSeek-V4-Pro-0813（real） |
| VLM | Qwen3.6-Plus（real） |
| 显式开关 | `--enable-real-api --i-approve-budget` + `STORY_API_ENABLE=1` |
| 上限 | max_rounds=1, max_calls=8, max_cost_usd=1.5, max_completion_tokens=2048 |
| 本轮实测 | http_attempts=5, real_ok=2, real_failures=3, est_cost_usd_real≈**0.0083** |
| mock 冒充成功 | **否**（`agent_claimed_success=false`） |
| 冻结 EDL/MP4 | **未修改** |

## 调用记录摘要

### LLM Planner（real）

- `provider_mode=real`，模型 DeepSeek-V4-Pro-0813
- 诊断（验证后 4 条）：
  1. **P0** 缺 `opponent_opening` 进球动作（记分牌不可顶替）— 与 Stage-1 一致
  2. **P1** `atom_fill_0004_Goal_1351642@1351.642` 仅为预测候选，**尚未视觉落地** — 规则 Stage-2 未把该原子写成提案证据；模型主动从因果样本提出待核验风险
  3. **P1** 0:1 节拍从记分牌开始，缺动作→比分因果衔接
  4. **P2** 标题卡 media 为空（占位）
- 视频工具：对 `score_node:behind_start` 发起 `vlm_observe`（窗由代码从 1535.65 锚点展开，首窗 **[1355.65,1385.65]**）
- revision_intents 本轮为空（仅工具请求）；未自创比分/绝对时间戳

### VLM（real）

- `provider_mode=real`，`fact_verified=false`，`observation_only=true`
- 窗口 [1355.65, 1385.65] 真实抽帧
- **可见内容要点：** 澳队球员边路活动；记分牌仍为 **France 0-0 Australia**（约 08′）
- 与人工 QC「Goal@1351 非破门、板仍 0:0」一致；**不能**据此宣称找到开场失球 LIVE

### Verifier（失败，如实记录）

- 第二次 Planner 角色调用遇 **代理 502 Bad Gateway** → `provider_mode=degraded`
- **未**用规则结果冒充模型 Verifier 成功
- 接受决策：`accept=false`（P0 仍在、无安全 EDL 修订、Verifier 失败）

## 相对规则系统：模型多发现了什么

| 点 | 规则 Stage-1/2 | 本轮真实模型 |
|----|----------------|--------------|
| 缺 opponent_opening | P0 已有 | 确认并展开叙事解释 |
| Goal@1351 | Stage-2 提案**不**采为证据 | 模型**主动**标为未视觉核验候选（P1） |
| 1355 附近画面 | 规则未看帧 | VLM 观察：仍 0-0，非破门 |
| 标题卡空 media | 未升 P0 | 模型记 P2 占位风险 |
| 自动改 EDL | 禁止 | 本轮亦未接受修订（正确） |

## 修改是否改善故事质量

**否（本轮）。**  
候选 EDL 相对基线无硬门禁改善（P0 仍 1）；仅 pending 证据检索意图，未绑定真实进球 media 时间，故回滚/不接受。  
**有价值产物**是真实 Planner 诊断 + 真实 VLM 观察，可支撑下一轮有界搜索（避开把 1351 原子当 LIVE 事实）。

## 先前尝试

| 目录 | 结果 |
|------|------|
| `..._20261104` | Planner 超时（上下文过大）→ 已压缩因果样本后重试 |
| `..._20261104_r2` | Planner **real 成功**，但 action 别名校验过严失败；已改为别名映射 |
| `..._20261104_r3` | Planner+VLM real；Verifier 502；诚实失败 |

## 是否可进入下一步

| 项 | 状态 |
|----|------|
| 证明真实大模型参与决策 | **是**（Planner + VLM real） |
| 证明可核验的成片质量改善 | **尚未**（需更多轮证据绑定 + Verifier 成功） |
| A/B/C 扩展 | **暂缓**，先稳定 FR 多轮（含 Verifier） |
| render_ready | **false** |

下一步建议：在同一预算门禁下跑 max_rounds=2–3；Verifier 失败时允许有限重试但不降级冒充；仅在 VLM+帧 PTS 绑定后才写入候选 goal_action 段。
