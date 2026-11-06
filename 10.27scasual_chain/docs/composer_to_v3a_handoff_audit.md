# Composer → V3-A 证据继承与问题驱动修订（阿联酋 vs 阿曼）

**分支 worktree：** `story-va-v3a-composer-handoff-A`（基于 `story-va-v3a-fresh-e2e-a-20261105` @ `bcd0b28`）  
**范围：** 零付费代码 + 阿曼场回归测试；未调用付费 API；未重渲；未跑三轮 Agent。  
**冻结：** 未修改 V1/V2/V3-R 基线实现路径以外的交付语义；未覆盖历史实验产物。

---

## 1. 审计：`seg_opponent_opening_goal_action` 证据链路

### 1.1 已存在于 Composer / Phase5 EDL 的字段

以 fresh E2E 基线行为例（`…/05_v3a/_baseline_phase5/candidate_edl.json`）：

| 字段 | 示例 / 含义 | 证据等级 |
|------|-------------|---------|
| `media_in/out` | 1325.123–1347.123 | 规则裁窗 |
| `event_ids` | `causal:pred_0007:atom_fill_0004_Goal_1337123` | 事件关联 |
| `time_provenance` | `linked_live_goal_event` @ 1337.123；比分锚 1410.43 | 规则推断 |
| `evidence_refs` | `rule_fact` / `opponent_opening_live_goal`；Δscore≈−73.3s | 规则事实 |
| `selection_reason` | `opponent_opening_goal_near_behind_scoreboard` | 规则选择 |
| `render_eligibility` | `candidate_only` | 门禁 |
| `blocking_reasons` | awaiting_internal_media_verification / semantic_unverified / … | 未视觉核验 |
| `is_replay=false` | Composer 标签 | **非**视觉 LIVE 证明 |
| `goal_action_complete` | true（结构完整性） | 结构代理 |

`first_live_status` **不在** Composer 基线行上；仅 Agent 绑定后出现。

### 1.2 修复前 Planner 实际看到什么

`compact_context()` 的 `candidate_edl` brief **只保留**：segment_id、role、media 窗、event_ids、is_replay、shot_kind、beat。

**丢失：** evidence_refs、time_provenance、selection_reason、render_eligibility、blocking_reasons、frame_ids、goal 完整性、为何选此候选。

结果：Planner 容易对「所有进球」无差别发起 `vlm_observe`，且可能把 `is_replay=false` 误当成 LIVE 认证。

### 1.3 修复后传递内容

新增 `composer_evidence_handoff`（schema `composer_evidence_handoff_v1`），从 **现有 EDL 行投影**（`composer_reexecuted=false`），按进球动作段输出上述字段 +：

- `is_replay_basis`（明确 rule label ≠ first LIVE）
- `visual_verification_status`（默认 `NOT_VISUALLY_OBSERVED`）
- `suggested_planner_disposition`（KEEP / INSPECT / REPAIR / UNRESOLVED）
- `historical_observations`（若有 prior Qwen 观察，可复用且 `cannot_certify_first_live=true`）
- `evidence_grades` / `claims_forbidden`

每轮写入 `round_XX/composer_evidence_handoff.json`，并嵌入 `planner_context.json`。

---

## 2. 代码改动

| 文件 | 变更 |
|------|------|
| `algo/story_video_agent_v3/composer_evidence_handoff.py` | **新增** handoff 投影、视觉状态梯子、disposition 映射 |
| `algo/story_video_agent_v3/self_revise_agent.py` | `compact_context` 注入 handoff；Planner system 提示问题驱动决策；`ACTION_ALIASES` / `_normalize_action` / `validate_planner_output` 映射 KEEP\|INSPECT\|UNRESOLVED；每轮落盘 handoff |
| `tests/test_v3a_composer_handoff_A.py` | **新增** 阿曼场零付费回归 |
| `docs/composer_to_v3a_handoff_audit.md` | 本审计 |

**未改：** `narrative_composer.py` / Phase5 冻结算法；未重实现 Composer。

### Planner 决策映射（无第二套协议）

|  disposition | 现有 schema |
|--------------|-------------|
| KEEP | `revision_intents.action=keep` |
| INSPECT | `action=keep` + 定向 `video_tool_requests`（trusted edl anchor） |
| REPAIR | 必须具体 `search_add\|replace\|trim\|drop\|reorder`；单独 `REPAIR` 被拒 |
| UNRESOLVED | `mark_unresolved` |

禁止：对比分确认或 `is_replay=false` 自动升为 `FIRST_LIVE_VERIFIED`；禁止无差别重搜全部进球。

---

## 3. 测试结果（零付费）

```
test_v3a_composer_handoff_A.py     7 OK
test_v3a_self_revise_agent.py      6 OK
test_v3a_fresh_e2e.py              9 OK
test_v3a_A_planner_diagnostic.py   3 OK
test_v3a_hybrid_fallback.py        8 OK
```

覆盖：

1. Composer 字段完整进入 Planner context  
2. 开场进球建议 `INSPECT` 且可解释（非 blanket research）  
3. 仅 KEEP、无新证据 → EDL 媒体窗/纳入剪辑不变  
4. 历史 Qwen 观察 → `HISTORICAL_VLM_OBSERVATION_ONLY`，不得冒充首次 LIVE  
5. 原有接口兼容（additive handoff）

---

## 4. 剩余问题

1. **Rule fallback Planner**（API 失败时）仍可能产出空 diagnoses；handoff 未强制 rule fallback 读取 disposition（可后续接 `hybrid_fallback`）。  
2. 历史观察复用：单轮实验可通过 `--seed-observations` 注入 smoke observation（见 `docs/v3a_one_round_readiness.md`）；仍不计新 HTTP、不升 FIRST_LIVE。  
3. `INSPECT` 有观察后仍不自动 `FIRST_LIVE_VERIFIED`（有意保留）；完整 LIVE 门禁仍待 Verifier + 多帧证据闭环。  
4. 付费单轮需单独授权；零付费就绪见 `v3a_one_round_readiness.md`。

---

## 5. 结论

证据继承缺口已在 V3-A 层以结构化 handoff 补齐；Planner 决策改为问题驱动并映射到现有 schema。  
**下一步（需单独授权）：** 阿曼开场进球 **单轮** 真实 Agent 闭环（max_rounds=1，HTTP≤3，$0.05），验证 INSPECT→可选 VLM→Verifier 相对 fresh V3-R 是否有可证实增益。
