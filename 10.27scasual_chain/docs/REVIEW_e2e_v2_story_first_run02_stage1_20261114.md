# Run02 Story-First Stage-1 — evidence-based semantic review

审阅日期：2026-11-14。评判准则来自 `STORY_FIRST_STAGE1_RUN02_PREREG_20261114.md`，不是看到输出后另设标准。

## 结论：STAGE1_PARTIAL — one narrative lead for investigation, zero verified causal stories

**这是模型提出了两条原始故事假设，不是算法最终接受两条；目前没有证明“能够提出两三条有独立机制、值得视频核验的长程故事”。**

- 原始模型：DeepSeek-V4.1-Flash，1 HTTP，64,206 输入 / 398 输出 / 0 reasoning tokens，finish_reason=stop，估算费用 $0.00987。
- 官方程序结果：`NO_VALID_HYPOTHESES`，0 accepted / 2 rejected，`observation_plan.targets=[]`，不可改写历史。
- 解析失败直接原因：Compact Prompt 把 `proposed_long_range_relations` 和 `observation_queries` 描述成“EXACTLY one object”，把 `falsification_conditions` 描述成一个条件；而验证器要求三个字段都是非空 **list**。三处都是 Prompt 与 Parser 合同不一致，不能将其归责为模型故事能力不行。不要把修正 JSON 后的 accepted count 冒充通过语义评测。
- 语义审阅依据为 `ARTIFACT_run02_llm_raw_response.txt`、`ARTIFACT_run02_cited_events_metadata.json`、Run02 工程报告和用户提供的冻结 V3-R plan 摘要；**没有审阅源视频**或服务器上的完整原 `story_plan.json` 正文。

## H1: penalty_var_denial_precedes_equalizer

模型声称“点球被 VAR 取消后，主队情绪与攻势可能延续，最终促成扳平”。

证据顺序：`event_000617` Penalty_Foul @6020.63；
`event_000622` Penalty_Disallowed_(VAR) @6196.82（known_replay_or_slowmo=true）；
`event_000635` Interception @6405.03；`event_000636` Interception @6410.07。
模型长程关系 617→635 跨越约 **384.40 秒**。
冻结 V3-R equalizer 动作候选 @6448.924s，模型选的 probe `event:event_000635` 对应 [6397.03, 6413.03]。

- Grounding：ID、顺序、VAR 标签真实；但引用元数据没有足够证据确认“主队”归属、情绪延续、攻势持续或事件之间的因果方向。模型使用“情绪”违反了预注册中不编造心理的要求。
- Long range：跨越几分钟，满足**时间跨度**，不代表因果成立。
- Falsification：检查 VAR 后持续进攻是合理的判别方向，但单一 16s 拦截 probe 不可能证明从 VAR 到扳平间“持续施压”；也不足以支持 VAR 引起攻势的因果效应，需要完整前后事件统计/多窗口视频观察及对照。
- Novelty：原 V3-R 已围绕逆转/扳平组织结构，VAR 取消点球这一**具体反转情节**在提供的冻结 plan event 集之外，具有**一个值得调查的新增叙事线索**。
- Critical risk：`event_000622` 是 REPLAY 类元数据对应的事件；不能将其所在 PTS 当作首次直播镜头或实时 VAR 决策时刻，也不能用于 EDL。需首先回溯直播中的真实 VAR 判决表达与时间；否则该新故事转折连合法视频素材都不具备。
- 阶段结论：**INVESTIGATE_ONLY**；有一条潜在新增故事情节，但因果说法、团队归属与视频合法性全部未验证。

## H2: substitution_then_sustained_pressure

模型声称“换人之后主队可能改变进攻组织，为扳平积累压力”。

证据顺序：`event_000563` Substitution @5557.60；
`event_000564` Substitution @5561.00；
`event_000598` Long_Pass @5841.34；
`event_000605` Aerial Duel @5919.20。
模型长程关系 563→605，跨越约 **361.60 秒**；只拟观察 [5833.34, 5849.34] 的一条长传。

- Grounding：ID 和时间先后真实，但引用的元数据不足以确定换人球队、换上球员及其参与度、长传与争顶的球队归属。
- Long range：确实跨越较长时间；**事件发生在换人之后 ≠ 换人导致进攻方式改变**。
- Falsification：模型给出前后攻势密度与推进方向对照的思路，但它计划的单个长传 probe 无法执行这种前后对照。必须有双方归属、多个赛段、对齐的观察与一个基准窗口。
- Novelty：有新增事件 ID，但“换人后施压、扳平”是通用体育叙事模板，尚无证据说明这场比赛中存在独特的战术转变；不满足强新增叙事价值。
- 阶段结论：**GENERIC_UNSUPPORTED**；只保留作替代假设，不进入昂贵视频核验优先队列。

## 两条假设的区分度

表面上起因不同（VAR 判罚 vs 换人调整），但落脚都是“先前刺激 → 主队持续施压 → 扳平”，缺少实证的中间状态与差异性预测。机制名称不同不能自动算两条独立成立的故事。两者都是后半段同一进球前的解释，不能证明模型具备跨多阶段的全局故事重构能力。

## 五项预注册门槛

| Gate | H1 | H2 |
|---|---|---|
| Grounding | IDs/PTS yes; emotion/team/causality unsupported | IDs/PTS yes; team/player causal link unsupported |
| Long range | 384.40s temporal yes, causal no | 361.60s temporal yes, causal no |
| Falsifiability | test idea yes; actual 16s probe insufficient | before/after idea yes; one post-pass probe insufficient |
| Novelty vs V3-R | specific canceled penalty reversal has investigative value | extra event IDs only; template-like |
| Mechanism diversity | different antecedent but shares pressure→goal explanation | same generic downstream explanation |

依照预注册：仅 H1 提供 **one investigative narrative lead**；所以定为 **STAGE1_PARTIAL**，不是 STAGE1_PASS，**0 verified causal stories**，**0 approved clips**，**0 new EDL cuts**。该判定仅基于开发集、单场赛事及所能审阅的 V3-R 对照摘要；未确认完整 plan 的所有细节，新增性仍待复核。

## 立即后续：零付费审计，而非端到端集成

1. 保留 Run02 原始 `NO_VALID_HYPOTHESES` 结果与 raw（不可回写）；修正 Prompt/Parser 的单元素数组类型合同并添加离线回归测试，不能把协议恢复当作语义通过。
2. 使用**已落盘 raw**做独立的 `OFFLINE_SCHEMA_RECOVERY` 诊断，以显式、字段级、可审计的方式将三种单值转换为单元素数组；不发 API、不删除原始字段、不覆盖 Run02。此步骤只判断结构可否恢复，不改变 PARTIAL 语义结论。
3. 零 HTTP 回查完整 frozen story_plan 与原子事件 enrich 的 team/player/phase 字段，核验 H1 的 VAR/live 事件链是否真实发生、所述哪一方、是否有首次直播合法镜头的可能；并检查 H2 的换人所属球队及其与后续事件的对应性。
4. 在此之前**不要**将 H1/H2 进入 EDL，不做自动故事提升、不运行昂贵的成片/多模态证据核验，也不要发新付费 LLM。
5. 若 H1 在完整事件上确实形成有根据的可剪故事转折，才设计有限预算、跨窗口、first-live 审核的独立 Video-Stage2 检验；H2 目前仅作为弱对照。
