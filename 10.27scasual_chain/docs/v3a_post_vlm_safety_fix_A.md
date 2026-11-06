# V3-A Post-VLM 安全修复报告（零付费）

**修复分支：** `story-va-v3a-post-vlm-safety-fix-A`  
**基线：** `story-va-v3a-post-vlm-revision-A` @ `860fbfdde843a690ba288a67304c179375693e62`  
**范围：** 限定安全修复；不重构 Agent；不新增大模型阶段；**HTTP=0 / $0**

---

## 问题根因与修复

### 问题 1：Verifier 失败仍可能更新 best

**根因：** `decide_accept()` 在 `goal_binds && sem != PASSED` 时，即便 `verifier.ok=False` / `NOT_EVALUATED`，仍可能走 `loop_pending_verification` 且 `accept=True`，主循环随即写入 `best["edl"]`。

**修复：**

- Verifier API 失败或语义 `NOT_EVALUATED|UNKNOWN|DEGRADED`：`accept=False`，`loop_retain=False`。
- 若存在 evidence-bound / soft 编辑：仅 `pending_proposal_only=True`，写入 `round_XX/pending_proposal.json`（研究档案），**不**更新 best。
- Verifier 明确 `quality_delta_vs_baseline=regressed`（或等价）：直接拒绝，无需额外 P0。
- Verifier 明确通过：维持原有接受门禁。

### 问题 2：trim 仅用四帧 min/max PTS

**根因：** `apply_candidate_revision()` trim 分支用匹配 issue 的帧 PTS 取 min/max±1s，稀疏观察即可强制缩短长窗。

**修复：** 新增 `evaluate_trim_bounds()`：

- 观察必须与目标 segment / issue / 时间窗对应。
- `live_or_replay=replay` 不得作为首次直播进球 trim 依据。
- 必须具备 shot+net，以及**明显短于原窗**的 `candidate_goal_action_span`，且至少 2 个 PTS 落在 span 内。
- 否则 `pending_evidence_slot` / reject，不强制 trim。
- `first_live_status=NOT_VERIFIED`；不设 render_ready。

### 问题 3：evidence_refs 模糊匹配

**根因：** `_evidence_refs_ok()` 允许 startswith/endswith/substring，标签即可混过。

**修复：**

- 仅 **exact token** 匹配。
- PROPOSE_REPAIR：非空 + 至少一条 concrete（request_id / frame_id / edl:seg / event），且与 `target_segment_id` 可追溯关联。
- KEEP / UNRESOLVED：允许空引用；不产生 EDL 时间修改。

### 问题 4：回滚测试

新增 `tests/test_v3a_post_vlm_safety_fix_A.py`，经 `run_self_revise` 主循环断言 `best_candidate_edl.json` 的 row-SHA 与修改前一致：

1. Verifier API 失败 + evidence-bound 候选 → best 不变；可有 pending_proposal。  
2. Verifier 质量下降（无额外 P0）→ best 不变。  
3. Replay 观察提出 trim → best 不变。  
4. 空 / 伪造 / 模糊 / 无关 evidence_refs → 拒绝；主循环 fail-closed，best 不变。  
5. 合法候选 + Verifier 通过 → 仍可接受。

---

## 测试结果

```
Ran 85 tests … OK
```

覆盖：safety_fix + post_vlm_revision + one_round + handoff + self_revise + agent_loop + hybrid + p0 + verifier_loop_relax + fresh_e2e。

原 78 项回归保留并通过；新增安全用例计入 85。

**实际 HTTP=0，费用=$0。未开展付费实验。**

---

## 关键代码

| 文件 | 变更 |
|------|------|
| `self_revise_agent.py` | `decide_accept` 门禁；`evaluate_trim_bounds`；pending_proposal 落盘 |
| `revision_planner.py` | 严格 evidence_refs |
| `tests/test_v3a_post_vlm_safety_fix_A.py` | 主循环回滚用例 |
| `tests/test_v3a_hybrid_fallback.py` / `test_v3a_verifier_loop_relax.py` | 对齐新语义 |
| `docs/v3a_post_vlm_safety_fix_A.md` | 本报告 |
