# End-to-End v2: Story-First × Enhanced V3-A Evidence Search 接线说明

日期：2026-11-14。分支：`story-va-e2e-v2-story-first-20261114`。

## 设计决定（架构，不是 Story-First 算法验收）

- **v1（冻结）**：原子事件补充 → V3-R 固定故事 → **增强版 V3-A 完整闭环**（Global Story Critic、原 Issue-driven Search、Planner、EDL、Renderer、双视频 Verifier、VLM 进球核验、Narrative Fit、独立 FIRST_LIVE 门禁）。禁止修改 `story-va-e2e-v1-frozen-20261114`。
- **v2**：上述相同主链，在 Evidence Search 阶段增加独立的 **Story-driven / Story-First** 分支。V3-R 主故事不重选；Story-First 只探索既定故事可能遗漏的重要长程关系或情节，可以输出零候选。
- **复用**：两种搜索将来可进入同一证据核验、Planner、渲染及 Verifier；绝不创建第二套故事生成器、第二套 Planner 或第二个自修订闭环。

## 当前代码接线（仅安全接口）

```text
V3-R fixed plan / EDL + enriched events / raw source video
          |
Enhanced V3-A Global Story Critic & Observation
          |
Evidence Search in story_e2e_agent.py
    +-- Existing Issue-driven Search --> old SearchResult --> old Planner
    |
    +-- V2 Story-First branch (opt-in, import POC artifacts)
          |-- validate POC anchor IDs and source PTS against current EDL
          |-- rebind entire event inventory and event source PTS
          |-- verify frozen story plan identity
          |-- revalidate model hypothesis IDs + observation query IDs
          |-- regenerate observation target PTS from current event code
          +-- write observation-only audit and 0 Planner candidates
          |
Old Planner --> old EDL safety / FIRST_LIVE --> Render --> old Verifier
```

**重要：当前 POC 尚无可靠的原始视频 SHA 绑定，也未进行视觉语义/因果/叙事增益核验。** 即使成功读入了假设，也不会自动进入原有 Planner 的候选池。新分支只输出 `02_round_NN/story_first_evidence_search.json` 及 round metadata；原 `search_report` 传给 Planner 的对象保持不变。此举使禁用分支的 v1 行为可做回归比较。

## 文件

- `algo/story_video_agent_v3/story_first_evidence_adapter.py`：只读 POC 导入、来源/锚点/事件核对、观察目标重建、fail-closed 审计。
- `algo/story_video_agent_v3/story_e2e_agent.py`：在原 Evidence Search 结束后调用 V2 分支，不修改诊断、Planner、渲染、Verifier 的业务逻辑。
- `algo/story_video_agent_v3/story_e2e_cli.py`：增加 `--story-first-artifacts-dir` 显式 opt-in。
- `tests/test_v3a_v2_story_first_evidence_adapter.py`：独立测试正例、零假设、过期事件、变化的 Story Plan/锚点、缺失产物、默认禁用。

## 使用方式

1. 先通过现有 `story_first_poc_cli.py` 在独立目录生成 POC，至少包含：
   `prepared_story_input.json`、`story_hypotheses.json` 和 `observation_plan.json`。
2. 运行增强版 V3-A 原有 CLI 参数，额外传入 `--story-first-artifacts-dir /path/to/POC_DIR` 即可。**无该参数时新分支不启动**。
3. 查看 `02_round_01/story_first_evidence_search.json`。成功匹配为 `OBSERVATION_QUEUE_ONLY` 或 `NO_VALID_HYPOTHESES`；过期输入则 `REJECTED_NO_PROMOTION`。
4. 目标单测（需在有完整仓库和 Python 环境的服务器运行）：

```bash
cd 10.27scasual_chain
PYTHONPATH=algo python -m pytest -q tests/test_v3a_v2_story_first_evidence_adapter.py tests/test_v3a_story_first_poc.py
```

## 尚未实现（后续讨论 Story-First 算法时决定）

1. 故事条件下的长程因果发现方法，不依赖默认首两个进球作为唯一搜索范围。
2. 主动视频观察、可反驳的长程因果验证和具体叙事增益判别。
3. 经独立 FIRST_LIVE 与 Narrative Fit 检验后的修订候选统一转换接口。
4. EDL 真实修订与成片质量的 v1/v2 同输入对照实验。

目前**只有集成边界，不等于 Story-First 算法开发完成或端到端 v2 验收通过**。
