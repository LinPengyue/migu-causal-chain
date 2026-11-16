# Scheme A Causal-4 预检阻断（2026-11-16）

HEAD: `ca4c83905a3a35b44cbef1bbbc4efa9d8e5694c2`  
组合目标：Generator=`55054a3` 区间局部情节发现；Scorer=四维 Causal（30/30/25/15）；无 Novelty / 无 Event-Grounding。

**本轮未发起任何付费 LLM 调用。**

## 1. Pytest

命令覆盖：

- `tests/test_v3a_story_first_scheme_a.py`
- `tests/test_v3a_v2_story_first_evidence_adapter.py`
- `tests/test_v3a_story_first_poc.py`
- `tests/test_v3a_story_first_local_patterns.py`

结果：**48 passed / 1 failed**

失败：

```text
tests/test_v3a_story_first_scheme_a.py::test_scheme_a_ranking_integrates_to_observation_queue_only
AssertionError: assert 'REJECTED_NO_PROMOTION' == 'OBSERVATION_QUEUE_ONLY'
```

### 根因（兼容性）

四维 Causal Scorer（`story_first_a_ranker.py`）现在要求文本字段：

- `causal_mechanism`
- `major_uncertainty`

并使用轴：`internal_causal_link` / `anchor_causal_bridge` / `joint_causal_gain` / `factual_support`。

但 Evidence Adapter（`story_first_evidence_adapter.py` ~188）重建评分时仍读取旧字段：

- `new_story_information`
- `comparison_to_existing_story`
- `major_uncertainty`

**未传入 `causal_mechanism`**。因此 `rank_model_evaluations` 重算时报
`missing_or_oversized_reason:causal_mechanism`，适配器吞掉异常后返回
`REJECTED_NO_PROMOTION`，观察队列被清空。

日志：`/tmp/lpy1_scheme_a_causal4_pytest_20261116.txt`

## 2. V3-R EDL 相邻语义节点（零付费）

输入：Run02 同款  
`/tmp/lpy1_v3a_p14_cv_integration_20261113/run/01_initial_story/candidate_edl.json`

| 观察 | 事实 |
|------|------|
| `story_anchor=true` 标记 | **0**（本 EDL 无显式语义锚点标记） |
| 回退 `*goal_action*` 节点 | **3**：opening / equalizer / go_ahead |
| 默认 `select_story_interval` | **可靠**：opening→equalizer，`[1347.123, 6436.924]` |
| 相邻 goal_action 第二对 | equalizer→go_ahead，`[6458.924, 6829.456]`（~370.5s） |

结论：实验区间**可以可靠识别**（legacy goal-action 回退有效）。若只因“节点无法识别”不会阻断付费；本轮阻断原因是 **Scorer↔Adapter 契约不兼容**。

### 默认实验区间（若修复后继续）

- from: `seg_opponent_opening_goal_action` (`opponent_opening_goal_action`)
- to: `seg_equalizer_goal_action` (`equalizer_goal_action`)
- source_interval_sec: `[1347.123, 6436.924]`

## 3. 付费状态

**STOPPED_BEFORE_PAID** — 需 ChatGPT 先修复 Adapter（写入 `causal_mechanism`、去掉对旧 novelty 文本字段的硬依赖）并让该回归变绿，再执行 Generator+Causal Scorer 实呼。

未修改历史实验产物、EDL、v1。
