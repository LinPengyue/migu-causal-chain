# Story-First Scheme A — Stage1 零付费回归（2026-11-15）

基准：`dd5d23d895af68a0538e4b2d0f6f074287c79aab`（`story-va-e2e-v2-story-first-20261114`）  
新输出根目录：`/tmp/lpy1_story_first_scheme_a_stage1_reg_20261115/`  
未改算法；未付费；未覆盖 `/tmp/lpy1_story_first_v2_deepseek_run02_20261114/`。

## 1. Git / pytest

| 项 | 值 |
|---|---|
| HEAD | `dd5d23d` |
| v1 frozen tip（只读确认） | `e0a5599` 仍在 `origin/story-va-e2e-v1-frozen-20261114` |
| pytest | **42 passed / 3 failed** |
| 日志 | `/tmp/lpy1_story_first_scheme_a_stage1_reg_20261115/pytest.log` |

失败（原始断言，未改代码）：

1. `tests/test_v3a_story_first_scheme_a.py::test_scheme_a_ranking_integrates_to_observation_queue_only`  
   篡改 `model_priority_0_to_1` 后期望 `REJECTED_NO_PROMOTION`，实际仍为 `OBSERVATION_QUEUE_ONLY`。
2. `tests/test_v3a_story_first_poc.py::test_compact_stage_one_prompt_and_minimal_hypothesis_fixture`  
   期望 prompt 含 `EXACTLY one object`，当前文案为 `Return exactly one compact JSON object`。
3. `tests/test_v3a_story_first_poc.py::test_run02_offline_cli_does_not_touch_history_or_network`  
   二次写入非空 out-dir 时 `argparse` `SystemExit: 2`，测试未按 `!= 0` 正常捕获。

## 2. Run02 离线 Schema 恢复

| 项 | 值 |
|---|---|
| 历史状态 | `NO_VALID_HYPOTHESES`；accepted 0 / rejected 2 |
| raw 假设数 | **2**（未重调 LLM） |
| 恢复目录 | `…/schema_recovery/` |
| 结构恢复 | `SINGLETON_ARRAY_SHAPE_ONLY_V1`；converted_count=**6** |
| parse_hypotheses | status `UNVERIFIED_HYPOTHESES`；**H1+H2 结构接受**；rejected 0 |
| story_stage1_passed | **false**（显式） |
| event_id | 8 个引用均在 inventory；无缺失 |
| REPLAY | H1 含 `event_000622`（`broadcast_phase=REPLAY` / `is_replay_metadata=true`；score 侧 `known_replay_or_slowmo=true`） |
| Scheme-A 评分输入 | **结构上可用**（非语义通过） |
| 历史 Run02 SHA | 恢复前后一致，未改写 |

## 3. Scheme-A 请求生成（零 HTTP）

```text
PYTHONPATH=algo python -m story_video_agent_v3.story_first_a_ranker \
  --prepared-story-input /tmp/lpy1_story_first_v2_deepseek_run02_20261114/prepared_story_input.json \
  --story-hypotheses …/schema_recovery/schema_recovery_hypotheses.json \
  --out-dir …/scheme_a_ranking
```

结果：`PREPARED_ONLY_ZERO_HTTP`，`http_attempts=0`，`selected=[]`  
产物：`score_model_input.json`、`scheme_a_audit.json`、`scheme_a_story_ranking.json`（AWAITING 空排行）

## 4. 评分输入字段审计

`score_model_input.messages[1]` user JSON 键：

- 有：`story_scope`（前后锚点 role/segment + `source_interval_sec` [1347.123, 6436.924]）
- 有：`event_context`（8 条：id / pts / type / label / known_replay_or_slowmo）
- 有：`candidate_stories`（H1/H2 + 未验证 relations）
- 有：system 要求 `anchor_fit` 与 `marginal_narrative_gain` 轴

缺失 / 缺陷：

| 问题 | 事实 |
|---|---|
| 完整 Story Plan | `frozen_story_plan` 来自 `story_plan_reference`，为 **9000 字符截断字符串**；原 plan ≈49575 chars；**不是合法 JSON** |
| 显式当前 EDL | `build_score_messages()` **无** `current_edl` 字段；EDL 仅可能残存在截断 plan 字符串的 `candidate_edl` 片段中 |
| 事件描述 | 8 条 `description` 均为 `""`/`null`，仅有 type/label |
| 模型因果解释 | H1/H2 relations 带 `UNVERIFIED_MODEL_HYPOTHESIS` claim；原子事件只提供事件事实，不支持因果 |

结论：Anchor Fit 有锚点时间窗可比；**Marginal Narrative Gain 缺少完整、可解析的现有故事/EDL 比较基准**。

## 5. 代码问题（行号，不修复）

| 文件 | 行 | 问题 |
|---|---:|---|
| `story_first_hypotheses.py` | 60–67, 274–279 | `_text(..., 9000)` 截断 plan → 损坏 JSON |
| `story_first_a_ranker.py` | 41–108 | `build_score_messages` 未传入完整/显式 EDL；依赖截断 `story_plan_reference` |
| `story_first_evidence_adapter.py` | 196–219 | ranking 不可复现时抛错被 except 只改 `reason`，**不**把 status 置为 `REJECTED_NO_PROMOTION` |
| `story_first_schema_recovery_cli.py` | 77–80 | 非空 out-dir 用 `parser.error` → `SystemExit` |
| `tests/test_v3a_story_first_poc.py` | ~421 | 断言文案 `EXACTLY one object` 与 prompt `Return exactly one compact JSON object` 不一致 |

## 6. v2 接线与隔离（只读确认）

- Scheme-A / Story-First：`story_e2e_agent.py` 1174–1195 为 **opt-in** 第二 Evidence Search 分支；只写 `story_first_evidence_search.json` + round 摘要；注释写明不改旧 Search→Planner 字节结果。
- `planner_safe_story_first_summary`：`planner_candidate_count=0`，不传未核验假设给 Planner。
- ranker 输出行含 `first_live_certified=false`、`planner_eligible=false`。
- Issue-driven / turn-context search（1200+）仍独立存在。
- 本轮未改 EDL/渲染；v1 tip `e0a5599` 仍在。

## 7. 是否具备真实 LLM 评分条件

**否（NOT READY）。**

阻断：pytest 3 红；评分上下文 plan 截断且非 JSON；无显式 EDL 比较基准；事件 description 空；语义上 Stage1 仍为 PARTIAL/未视频验证。结构恢复仅说明可喂入 ranker prepared-only，不构成付费授权。

## 路径索引

- 回归根：`/tmp/lpy1_story_first_scheme_a_stage1_reg_20261115/`
- pytest：`…/pytest.log`
- 恢复：`…/schema_recovery/`
- 评分请求：`…/scheme_a_ranking/score_model_input.json`
- 摘要 JSON：`…/STAGE1_REGRESSION_SUMMARY.json`
- 历史 Run02（只读）：`/tmp/lpy1_story_first_v2_deepseek_run02_20261114/`
