# V3-A Agent Self-Revise（真实 LLM + VLM）

**分支：** `story-va-v3-a`  
**冻结基线：** `story-va-v3-r-frozen-20261103` @ `2d1ec9c`（只读）  
**模块：** `algo/story_video_agent_v3/self_revise_agent.py`

## 目标转向

从「规则诊断 + 任务排序」转向 **真实大模型参与决策的故事自修订 Agent**。Stage-1 硬门禁与 Stage-2 离线提案保留为基线输入，不再作为主研发方向继续堆规则。

## 闭环

```
Planner(LLM) → 视频工具/抽帧 + VLM观察 → 候选EDL修订(工作副本) → Verifier(规则硬门禁+LLM语义) → 接受或回滚
最多 3 轮；全程记录 I/O 与费用。
```

## 硬约束

| 约束 | 说明 |
|------|------|
| 不编造事实 | 禁止自创比分、进球事实、自由时间戳 |
| 可信锚点 | 搜索窗必须引用 `trusted_anchors`（T01 比分节点 / 现有 EDL） |
| 观察≠核实 | VLM 不得将单次描述升级为 first LIVE / 进球已核实 |
| 冻结保护 | 不改 V3-R phase5 / 不自动重渲；输出仅在 `--out-dir` |
| 付费门禁 | 需 `--enable-real-api` + `--i-approve-budget` + `STORY_API_ENABLE=1` |
| 诚实失败 | API/解析失败如实记录；禁止用 mock/cache/规则冒充 Agent 成功 |

## 本地单测

```bash
PYTHONPATH=10.27scasual_chain/algo \
python -m unittest discover -s 10.27scasual_chain/tests -p 'test_v3a_*.py' -v
```

## 法国场最小真实实验

见 `V3_A_INCREMENTAL_REVISION_PLAN.md` 中 Pivot 命令。默认建议：`--max-rounds 1 --max-calls 8 --max-cost-usd 1.0`。

验收重点：**真实模型参与决策**，并产出可核验的故事质量改善证据；不是流水线 exit code。
