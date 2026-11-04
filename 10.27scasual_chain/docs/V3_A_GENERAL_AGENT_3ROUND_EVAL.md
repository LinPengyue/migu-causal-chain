# V3-A 通用故事视频 Agent：三轮自修订与四维 Verifier 评估

**分支：** `story-va-v3-a`  
**代码基线 SHA（实验运行）：** `2fc6b165f4b2b84a115d296689d3e061d6ff9ece`  
**实验样本（唯一付费）：** 法国 vs 澳大利亚（输入样本，非算法特例）  
**输出目录：** `/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_FR_france_australia_zeroshot/v3a_general_agent_3round_20261104`  
**控制台日志：** `…/v3a_general_agent_3round_20261104_console.log`  
**配置：** `max_rounds=3` · `max_calls=24` · `max_cost_usd=1.0` · `quality_threshold=75`（参考）· `--no-stop-on-quality-threshold` · 真实 Planner / VLM / API Verifier  
**正式交付：** `release_eligible=false` · `release_decision=NOT_AUTHORIZED` · `render_ready=false`（opening `first_live_status=NOT_VERIFIED`）

---

## 1. 执行流程与真实调用

三轮全部跑完（`rounds_executed=3`，`abort_reason=null`，未触达费用/调用硬上限）。

| 角色 | HTTP | tokens | est_cost_usd |
|------|------|--------|--------------|
| Planner（DeepSeek-V4-Pro-0813） | 3 | 56031 | 0.019014 |
| Vision（Qwen3.6-Plus） | 10 | 91044 | 0.015875 |
| Verifier（DeepSeek-V4-Pro-0813） | 3 | 22267 | 0.005550 |
| **合计** | **16** | **169342** | **≈0.0404** |

`real_ok=16` / `real_failures=0` / `mock_calls=0`。费用为本地单价估算，非账单保证。

每轮链路：Planner → VLM/视频工具 → Candidate Revision → Rule+API Verifier → Loop Controller。

---

## 2. 分轮：问题发现、行动、反馈继承

### Round 1（无 prior；`prior_feedback_consumed=false`）

**Planner 诊断（自主）：**

| 严重度 | 要素 | 摘要 |
|--------|------|------|
| P0 | missing_story_element | 缺 opponent opening goal action，仅有落后记分牌 |
| P1 | unverified_candidate_location | 预测因果原子未视觉确认 |
| P2 | possible_image_anomaly | title 卡片可能异常 |
| P2 | live_vs_replay_risk | 现有进球镜头 live/回放未核验 |

**行动：** `search_add` + 多窗 VLM；证据绑定 `seg_opponent_opening_goal_action` **1415.65–1445.65**（`CANDIDATE_BOUND_UNVERIFIED_FIRST_LIVE`）。  
**Loop：** **接受** `p0_repair`（coverage 66.7→100；P0 1→0）。`release_eligible=false`。

### Round 2（继承 R1；`prior_feedback_consumed=true`）

Context 含 `prior_round_feedback.from_round=1` 与 R1 `prior_observations`。诊断转向 **边界/镜头相关性** 与 **live_vs_replay**，而非重复“完全缺失 opening”。

**行动：** 对 opening 段 `replace` → **1415.65–1425.65**（证据绑定裁剪）；`mark_unresolved` live 视觉真值。  
**Loop：** **接受** `quality_improvement`。仍 `NOT_VERIFIED`。

### Round 3（继承 R2；`prior_feedback_consumed=true`）

Context 含 R2 诊断（边界偏晚、live UNKNOWN）与观察。Planner 再次尝试扩展 opening，并扩观察 equalizer / go-ahead / lead-extend。

**行动：** `replace` **未写入 EDL**（`bound_segment_requires_explicit_role` / `pending_evidence_slot`）；`mark_unresolved` 记录。  
**Loop：** **拒绝** `no_evidence_bound_or_safe_edit`。工作副本回退，**最佳保留 = Round 2**。

**反馈继承结论：** R2/R3 不是同一 Planner 空转；输入含上一轮诊断、观察与 Verifier 议题。R3 意图方向正确，但绑定门禁挡住了无 role 的猜测性写入。

---

## 3. 四维质量评分与回放风险

等权综合；**UNKNOWN/null 不计入均值**，不强制 0/100。

| 轮次 | coverage | coherence | image | live_authenticity | composite（含 UNKNOWN 排除） | 共同可评估维均值（cov+coh） | 接受? |
|------|----------|-----------|-------|-------------------|------------------------------|-----------------------------|-------|
| R1 | 100 (api) | 100 (api) | UNKNOWN | UNKNOWN | 100.0（2 维） | **100.0** | Y |
| R2 | 100 (api) | 100 (api) | UNKNOWN | UNKNOWN | 100.0（2 维） | **100.0** | Y |
| R3* | 66.7 (api) | 100 (api) | UNKNOWN | 80.0 (api) | 82.23（3 维） | **83.35** | N |

\*R3 为未接受候选上的 Verifier；跨轮公平比较以共同维 cov+coh 为准，避免因多评了 live 维而虚假抬/压分。

### `live_segment_assessments`（演进）

- **R1/R2：** opening 与多数进球段多为 `UNKNOWN` / score=null（VLM 单次观察不升格 `FIRST_LIVE_VERIFIED`）。
- **R3（拒绝候选上的诊断信号）：**

| segment_id | live_status | score |
|------------|-------------|-------|
| seg_opponent_opening_goal_action | UNKNOWN | null |
| seg_equalizer_goal_action | LIKELY_LIVE | 80 |
| seg_go_ahead_goal_action | LIKELY_LIVE | 80 |
| seg_lead_extend_1_goal_action | LIKELY_LIVE | 80 |
| seg_lead_extend_2_goal_action | UNKNOWN | null |

本轮 **无 CONFIRMED_REPLAY**；严重回放门禁未触发。opening 保持 `NOT_VERIFIED` → 发布门禁继续拦截。

---

## 4. EDL 修改与接受/拒绝

| 轮次 | 变更 | 状态 |
|------|------|------|
| Baseline V3 phase5 | 11 行；**无** opening goal action | — |
| R1 | +opening 1415.65–1445.65 | 接受 |
| R2 | opening → 1415.65–1425.65 | 接受（**best**） |
| R3 | 拟 replace 扩展边界 | **拒绝**（无显式 role / 证据门未过） |

冻结 `04_phase5` 未被改写（`edl_modified_frozen_phase5=false`）。

---

## 5. 是否真实迭代改善？

- **是（R1→R2）：** 缺要素修复 → 边界裁剪；R2 明确消费 R1 反馈。  
- **有限（R3）：** 诊断与观察继续深化（含多镜头 live 评估），但修订未落地；非无意义重复，亦非有效 EDL 改善。  
- API 自报 coverage 在 R1/R2 顶满 100 且部分维 UNKNOWN，**数值饱和**；结构改善主要靠 P0 修复与证据绑定计数，而非综合分跃迁。

---

## 6. 对照：V3-R / 既有 V3-A 单轮 / 本轮三轮最佳

| 来源 | Opening 镜头 | 备注 |
|------|--------------|------|
| V3-R / phase5 baseline | 无；仅 1534.65 落后记分牌 | 结构缺 opening |
| V3-A 单轮 adapter（`…r2_adapter`） | 1385.65–1415.65，`NOT_VERIFIED` | 1 轮接受；候选预览 ≈142s |
| **本轮三轮 best（R2）** | **1415.65–1425.65**，`NOT_VERIFIED` | 更短；R3 曾指边界偏晚但未改成功 |

三轮在通用反馈环上推进了诊断广度（live 维、多段观察），**未**在 opening 时间选择上稳定优于单轮 adapter；两边均不可正式交付。

---

## 7. 候选 MP4 / 费用 / 日志

| 项 | 路径 / 值 |
|----|-----------|
| story_clean.mp4 | `…/v3a_general_agent_3round_20261104/v3a_candidate_render/story_clean.mp4`（≈36MB，**121.93s**） |
| story_qc.mp4 | 同目录 `story_qc.mp4`（≈40MB，同时长） |
| RENDER_NOTE | `release_eligible=false`；候选预览，非正式交付 |
| best EDL | `…/best_candidate_edl.json`（best_round=2） |
| API | 16 calls · 169342 tokens · ≈$0.0404 |
| 运行墙钟 | ≈34.2 min（含抽帧/渲染前后） |

---

## 8. 其他比赛免费通用性回归

`tests/test_v3a_general_agent.py`：**5 passed**（四维分数保留 / UNKNOWN 排除 / prior_feedback 入 context / SEMANTIC_DIMS=4）。

另对 A/B/C phase5 各跑 1 轮 **degraded offline**（`enable_real_api=false`，`skip_vlm=true`）：

| 比赛目录 | workflow_completed | 冻结 phase5 | planner_context 含「法国」/australia | match_agnostic 约束 |
|----------|-------------------|-------------|--------------------------------------|---------------------|
| A 阿联酋vs阿曼 | true | 未改 | 否 | true |
| B 奥萨苏纳vs塞尔塔 | true | 未改 | 否 | true |
| C 克罗地亚vs加拿大 | true | 未改 | 否 | true |

未对其他比赛触发付费 API。核心算法路径无比赛名硬编码分支（仅注释提及 France 观测别名）。

---

## 9. 测试与 Git

| 项 | 值 |
|----|-----|
| 单元测试 | `python -m unittest tests.test_v3a_general_agent` → OK (5) |
| 实验代码 SHA | `2fc6b165f4b2b84a115d296689d3e061d6ff9ece` |
| 本评估文档提交 | `bc4ba573fa8f53f42e02635c86f196c7ec952d6d` |

---

## 最终三问

### A. 通用 Agent 能否自主发现不同类型故事质量问题？

**能（本样本内）。** 除缺失 opening 外，还提出未核验预测点、title 异常、镜头边界/相关性、多段 live/回放风险；问题集合随轮次从“缺要素”扩展到“边界与真实性”，且由当前 EDL/锚点/观察驱动，而非写死法国场剧本。

### B. 多轮 Planner–VLM–Verifier 反馈能否持续推动有效修订？

**部分能。** R1→R2 有真实接受的证据绑定修订与反馈继承；R3 继承正确但 **修订落盘失败**（role/证据门），未形成第三轮 EDL 改善。机制上多轮环路工作；持续有效修订仍受绑定约束与模型 intent 完整性限制。

### C. 首播真实性评分能否帮助主动发现并修正不合适回放镜头？

**发现：有信号；修正：本轮未完成。** R3 产出分段 `LIKELY_LIVE` / `UNKNOWN` 与维分 80，推动观察扩面；opening 仍 `UNKNOWN`+`NOT_VERIFIED`，无确认回放可替换，也无成功的 live 向 EDL 改写。回放维作为修订反馈有效，**不能**单凭 VLM 一次观察宣称 `FIRST_LIVE_VERIFIED`——与设计一致。

---

**总判：** 通用三轮 Agent + 四维 Verifier 在法国样本上完成真实付费闭环与 A/B/C 免费兼容；产生可保留候选预览但 **非正式交付**。观察重点是自修订机制能力，而非法国场定向刷分。
