# V3-A VLM 证据语义修复报告（零付费）

**基线**: `story-va-v3a-evidence-verifier-audit-A` @ `038c69c`  
**约束**: HTTP=0；不改冻结 EDL；不改四角色架构；不启动新实验。

---

## 根因（已证实）

1. **`observed_net` 语义歧义**：实现与提示曾将其与「进球确认」混用；NEW 真实 Qwen 响应在 `supports_bound_segment=false` 且叙述「未进球/0-0」时仍给出 `observed_net=true`。
2. **弱证据提升**：`authorize_bound_segment()` 用 `shot=true && net=true`（以及 `candidate_goal_action_span`）**覆盖**显式 `supports_bound_segment=false`，可错误授权进球动作绑定。
3. **记分牌 0-0**：曾被用作「未进球」启发式；稀疏帧上 0-0 既不能证明未进球，也不能证明已进球。

---

## 修复内容

### 1. 字段语义（`vlm_evidence_semantics.py`）

| 字段 | 含义 |
|------|------|
| `goalmouth_or_net_visible` / 旧 `observed_net` | 球门/球网结构可见 — **≠ 进球确认** |
| `observed_shot` | 射门尝试可见 |
| `ball_crosses_goal_line` | 球明显越过球门线（更强） |
| `goal_result_confirmed` | 进球结果已确认（最强） |
| `supports_bound_segment` | 模型显式认可绑定该窗为进球动作候选（仍非 FIRST_LIVE） |

分类结果：`SUPPORTS_CANDIDATE_BIND` / `AMBIGUOUS_EVIDENCE` / `LACKS_SUPPORT`。

### 2. `authorize_bound_segment()`

- **禁止** `shot&&net` 或 `candidate_goal_action_span` 覆盖 `supports_bound_segment=false`。
- 冲突/不明 → `evidence_status=AMBIGUOUS_EVIDENCE`，`allow=False`，不可用于进球动作证据绑定。

### 3. `build_bound_segment_from_observations()` / `evaluate_trim_bounds()`

- 进球角色：非 `bindable` 直接拒绝；模糊证据返回 `AMBIGUOUS_EVIDENCE`。
- Trim：`supports=false` 冲突立即 reject；不再仅凭 `shot+net` 裁剪。
- 无显式 supports 时拒绝「稀疏 PTS min/max」造段。

### 4. 记分牌 0-0

- 分类与提示明确：**单独既不证明进球、也不证明未进球**。
- Follow-up 调度改为基于证据分类，不再把「可见 0-0」当作 match-level 否定证明。

### 5. 完整可见输出落盘

- `persist_visible_model_output()` → `round_XX/model_visible/{role}_{id}.json`
- Planner / Vision / Revision Planner / Verifier 真实响应写入**完整** `content`
- 摘要 JSON 仍可保留短 `raw_excerpt`（≤2000）
- 红action：`api_key` / `Authorization` / data-URI base64 图像；不写密钥

---

## 回归（HTTP=0）

```text
PYTHONPATH=algo python3 -m unittest \
  tests.test_v3a_vlm_evidence_semantics_A \
  tests.test_v3a_evidence_verifier_audit_A \
  tests.test_v3a_post_vlm_safety_fix_A \
  tests.test_v3a_post_vlm_revision_A \
  tests.test_v3a_agent_loop_gaps \
  algo.story_video_agent.test_phase4b3_token_audit
```

| 结果 | 数量 |
|------|------|
| Ran | **56** |
| Passed | **56** |
| Failed | **0** |
| Errors | **0** |
| Skipped | **0** |

关键用例覆盖：

- OLD Qwen → `SUPPORTS_CANDIDATE_BIND`；NEW Qwen → `AMBIGUOUS_EVIDENCE`
- NEW 冲突不可 authorize / trim / build_bound
- `run_self_revise`：RP `UNRESOLVED` + EDL 未变 + `inject_verifier_failure=True` → 仍 `NO_CANDIDATE_CHANGE` 跳过（注入失败未触发）

---

## 未改 / 未解决

- 冻结 Phase5 EDL 未改。
- 四角色架构未改。
- 未付费重跑；未自动开新实验。
- Qwen 随机性本身未消除；靠门控阻止弱证据提升。
- 历史已落盘实验的 2000 字符 excerpt **不会回填**；仅后续真实响应写完整文件。
