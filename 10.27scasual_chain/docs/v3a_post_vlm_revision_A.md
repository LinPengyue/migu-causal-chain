# V3-A Post-VLM Revision Planner + Verifier 闭环

**分支：** `story-va-v3a-post-vlm-revision-A`  
**基线：** `story-va-v3a-composer-handoff-A` @ `063270df69a48a9b76d10c7a8fb0651fb32135a6`  
**范围：** 代码 + 零付费离线验证；**实际 HTTP=0 / 费用=$0**  
**未改：** 冻结 Phase5、V1/V2/V3-R、历史实验产物、原始 Composer EDL

---

## 1. 新执行流程与关键代码

```
Planner (DeepSeek)
  → VLM (Qwen)
  → Revision Planner (DeepSeek, stats_role=revision_planner)
  → 规则安全门禁 + apply_candidate_revision()
  → Candidate EDL
  → Verifier (DeepSeek + 规则) + decide_accept()
  → Accept / loop_retain / Reject（拒绝则回滚 best）
```

| 位置 | 作用 |
|------|------|
| `algo/story_video_agent_v3/revision_planner.py` | Prompt、schema 校验、上下文、fail-closed、intent 覆盖规则 |
| `algo/story_video_agent/api_provider.py` → `revise_decision()` | 复用 planner 端点，独立 `stats_role=revision_planner` |
| `algo/story_video_agent_v3/self_revise_agent.py` | 主循环插入 Revision Planner；审计 pre-VLM intents |
| `algo/story_video_agent_v3/one_round_opening_budget.py` | `ONE_ROUND_MAX_HTTP=4`（含 Revision Planner） |
| `tests/test_v3a_post_vlm_revision_A.py` | A–E 离线验收 |
| `tests/fixtures/v3a_post_vlm_revision_A/` | **模拟** fixture（非真实 DeepSeek 决策证明） |

CLI：`--enable-post-vlm-revision` / `--disable-post-vlm-revision` / `--revision-planner-fixture`  
`one_round_opening_goal` 默认开启 post-VLM；真实模式要求 `max_calls>=4`。

---

## 2. Revision Planner prompt / schema / 示例

**System prompt：** `REVISION_PLANNER_SYSTEM`（`revision_planner.py`）

**输出 schema（`v3a_revision_planner_output_v1`）：**

- `decision`: `KEEP_WITH_NEW_EVIDENCE` | `PROPOSE_REPAIR` | `UNRESOLVED`
- `target_segment_id`, `issue_id`, `diagnosis`, `reasoning_summary`
- `evidence_refs`（必须落在已知 observation/frame/composer token 白名单）
- `proposed_revision_intents`（经现有 `validate_planner_output` 规范化）
- `remaining_uncertainties`, `expected_improvement`

**KEEP 示例（离线 fixture）：** `tests/fixtures/.../rp_keep_opening_real_replay.json`  
**REPAIR 示例（synthetic）：** `rp_propose_trim_synthetic.json`  
**UNRESOLVED 示例：** `rp_unresolved.json`

输入上下文见 `build_revision_planner_context()`：best EDL、composer handoff、Planner diagnoses/intents/tools、历史+本轮 VLM、FIRST_LIVE 约束。

---

## 3. 新旧 Planner intents 区别与覆盖规则

| 来源 | 用途 |
|------|------|
| Pre-VLM `planner_revision_intents` | **仅审计**（写入 `intent_source.json` / round 记录） |
| Post-VLM `proposed_revision_intents` | **唯一**送入 `apply_candidate_revision` 的编辑输入 |

规则：

1. `enable_post_vlm_revision=True` 且 Revision Planner 成功 → 使用其 intents。  
2. Revision Planner 失败 / 非法 JSON / 伪造 evidence / 缺字段 → **fail-closed keep**；**禁止**回退到旧 Planner 的 trim/replace 等编辑。  
3. `enable_post_vlm_revision=False` → 兼容旧路径（pre-VLM intents 直接修订）。

---

## 4. 真实历史实验离线重放

复用：`/data2/lpy1/_story_va_outputs/v3/plan2/A_one_round_opening_20261106_133900`

- 真实 Qwen：`observed_shot=true`, `observed_net=true`, PTS ≈ 1334.64–1339.16  
- 模拟 Revision Planner：**KEEP_WITH_NEW_EVIDENCE**  
- 结果：EDL SHA 与 Composer 基线一致（`f259da7b…` / row-sha 不变）  
- 新证据记入上下文；无虚假 EDL 增益；未升 FIRST_LIVE  
- **未重新调用** Planner / VLM / Verifier / Revision Planner HTTP

---

## 5. A/B/C/D/E 测试结果

| 用例 | 结果 |
|------|------|
| A 原窗口合理 → KEEP | PASS（EDL 不变） |
| B synthetic 偏移 → PROPOSE_REPAIR trim + Verifier 允许 | PASS（候选变化且可 loop_retain/accept） |
| C 伪造证据 / 自由时间戳 / Verifier 拒绝 / 越界 PTS | PASS（拒绝；best SHA=修改前） |
| D 超时/非法 JSON/缺字段/注入失败 | PASS（fail-closed；无未验证编辑） |
| E 回归（handoff / self_revise / agent_loop / hybrid / p0 / verifier / fresh_e2e / one_round） | **78 OK** |

说明：全部 fixture 标有 `simulated_revision_planner_fixture`；**不能**声称已验证真实 DeepSeek Revision Planner 决策能力。

---

## 6. 候选 EDL diff / Verifier / 回滚 SHA

- A：候选 ≡ 基线；accept=false（无 evidence-bound edit）  
- B：trim 缩短开场窗；Verifier accept fixture → loop 可保留；`release_eligible` 不自动成立；非 FIRST_LIVE / 非 render_ready  
- C/D：拒绝后 `best` 与 `pre_revision_edl_sha256` 一致；冻结 Phase5 文件 SHA 未变

---

## 7. HTTP 与费用

| 项 | 值 |
|----|----|
| 实际 HTTP | **0** |
| 实际费用 | **$0** |
| 未来真实一轮预算 | Planner1 + VLM≤1 + RevisionPlanner1 + Verifier1 = **max_calls≥4** |

---

## 8. 现有测试

```
python -m unittest tests.test_v3a_post_vlm_revision_A \
  tests.test_v3a_A_one_round_readiness tests.test_v3a_composer_handoff_A \
  tests.test_v3a_self_revise_agent tests.test_v3a_agent_loop_gaps \
  tests.test_v3a_hybrid_fallback tests.test_v3a_p0_no_regress \
  tests.test_v3a_verifier_loop_relax tests.test_v3a_fresh_e2e
# → Ran 78 tests … OK
```

---

## 9. 尚未验证 / 下次真实实验前置条件

**尚未验证：**

- 真实 DeepSeek Revision Planner 在 shot+net 证据下是否会 KEEP（而非乱 trim）  
- 真实模型 PROPOSE_REPAIR 的叙事合理性  
- 四角色同轮真实计费与 abort 边界

**下次付费实验前置（需单独授权）：**

1. HEAD 在本分支；工作区干净  
2. `--enable-post-vlm-revision`（或 `--one-round-opening-goal`）  
3. `--max-calls 4`（或更大）、`--max-retries 0`、预算显式批准  
4. 输入视频 SHA 与 seed 校验 fail-closed  
5. 不自动渲染；不自动第二轮  
6. 禁止把 KEEP/单次 VLM/Verifier 自评分当作 Agent 成片成功  
7. `loop_retain ≠ FIRST_LIVE_VERIFIED ≠ render_ready`

---

## 重要限制（本阶段已遵守）

- 未修改冻结 Composer 基线  
- 无真实付费调用  
- `live_or_replay=live` ≠ FIRST_LIVE  
- 4 帧 shot+net ≠ 强制缩短 22s 窗  
- 不为展示「能改 EDL」而强制 REPAIR  
