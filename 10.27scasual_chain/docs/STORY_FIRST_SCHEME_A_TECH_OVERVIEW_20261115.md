# Story-First 方案 A：简短技术实现概述（2026-11-15）

## 目标

在 V3-R **已确定的故事主线和 EDL** 内，寻找当前成片尚未表达、但可能提高观众理解的关键事件组合；不重新选择故事，不按时间缺口、热度或单事件分数直接补镜头。集成位置为增强版 V3-A 的 **Story-driven Evidence Search**，原 Critic / Issue-driven Search / Planner / Renderer / Verifier 全部保留。

## 最小两阶段算法

**Step 1 · 候选故事生成（已有 Stage-1 POC）**：从 Story Plan/模板和指定的一对前后故事节点确定搜索区间，输入区间内完整原子事件索引。LLM 生成 0–K 个候选*增量情节*（每个引用 2–4 个真实 event_id），描述事件组合、与节点的关系及可反驳的观察问题。V3-R 主线冻结；所有因果、战术与情绪解释只是待验证假设。首次试验用明确 `--from-segment-id` / `--to-segment-id`，不把默认“前两个进球”视为通用故事节点选取策略。

**Step 2 · 独立 LLM 故事级评分（本次新增方案 A）**：另起一次评分请求，不让生成模型直接宣布自己的故事最好。对整条候选事件*组合*给出五个 0–4 的保守序数分：

- `anchor_fit`：与前、后既定故事节点的联系
- `internal_coherence`：候选内事件发展是否连贯
- `joint_composition`：整组事件相对于孤立事件的叙事作用
- `marginal_narrative_gain`：相比现有 EDL 预计新增了什么信息、是否冗余
- `event_grounding`：这些解释有多少能回溯到真实输入事件

仅作观察优先级的临时排序启发式（**不是校准过的客观因果分**）：

```text
C = (anchor_fit + internal_coherence + joint_composition) / 12
G = marginal_narrative_gain / 4
E = event_grounding / 4
priority = 0.45*C + 0.40*G + 0.15*E
```

对事件组合整体打分，**不**对各事件分别评分再累加；需引用真实 event_id、说明“相比原故事新增的信息”和最大不确定性。默认按优先级选 Top-2 **进入视频观察队列**，不是进入 Planner。允许零候选；单事件候选不作为“多事件组合”入选。

## 现有增强版 V3-A 的衔接

```text
V3-R fixed Story / EDL → Story-First Generate → Scheme-A Rank
→ （Top-K仅进入）Evidence Search 的目标视频核验队列
→ 未来：事实、长程关系、FIRST_LIVE、Narrative Fit 逐级核验
→ 原增强版 V3-A Planner → EDL → Render → Verifier
```

现阶段只实现至 **Top-K 未核验观察队列**。现有 `story_first_evidence_adapter.py` 可读取 `<Stage1目录>/scheme_a_ranking` 的评分产物，校验 Stage-1 文件 SHA 与排名可重算性，然后调整观察队列顺序；**绝不把模型分数作为已验证因果、视频证据或 Planner 候选**。模型分数未知时沿用原观察队列。

## 代码与实验边界

- `story_first_hypotheses.py`：沿用 Stage-1 事件约束候选生成（尚未实现通用 Story Graph 自动锚点选择）。
- `story_first_a_ranker.py`：新增独立故事级评分 CLI，默认零 HTTP；仅已配置共享服务和显式授权时能发起单次付费评分。
- `story_first_evidence_adapter.py`：可选接收评分报告，只改变 Story-First 的观察优先级，不影响原 Issue-driven Search / Planner。
- `tests/test_v3a_story_first_scheme_a.py`：验证真实 event_id 绑定、候选排序、过期/篡改拒绝、零付费默认、安全隔离。

**运行（默认准备评分请求，不发 HTTP）：**

```bash
cd 10.27scasual_chain
PYTHONPATH=algo python -m story_video_agent_v3.story_first_a_ranker \
  --prepared-story-input /path/STAGE1/prepared_story_input.json \
  --story-hypotheses /path/STAGE1/story_hypotheses.json \
  --out-dir /path/STAGE1/scheme_a_ranking
PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_story_first_scheme_a.py \
  tests/test_v3a_v2_story_first_evidence_adapter.py \
  tests/test_v3a_story_first_poc.py
```

**验收策略**：先检查模型能否区分高关联但低新增价值的候选、是否产生事实幻觉；再与事件重要性排序/时序摘要等基线比较；最后由真实原视频观察、首次直播安全门禁、试渲染及人工盲评检验实际增益。当前**没有新的真实 LLM 评分、视频核验或 EDL 增益结论**。历史 Run02 的 2 个原始假设因 Schema 不符正式接受数为 0；不得将离线结构修复当成新模型结果或因果证明。v1 分支和历史 BEST 不改。
