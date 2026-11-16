# Scheme A Causal-4 实跑（Generator 55054a3 + 四维 Causal Scorer）

HEAD: `48191eac04fa5faa18377b5674d5fafecf98b7ff`  
Server out: `/tmp/lpy1_scheme_a_causal4_run_20261116/`  
Artifacts: `docs/artifacts_scheme_a_causal4_run_20261116/`  
区间：opening→equalizer `[1347.123, 6436.924]`（与上一轮对照）  
组合：区间局部情节发现 Generator；四维 Causal Scorer（30/30/25/15）；**无 Novelty / 无 Event-Grounding**；无 VLM / 未改 EDL / 未进 Planner。

## 预检

| 项 | 结果 |
|----|------|
| Story-First pytest | **49 passed** |
| 输入 SHA | EDL `b38434b9…` / plan `ba64c215…` / events `33958b10…` **PASS** |
| Gen measured tokens | **64614**（官方 encode_messages chat + tokenizer.json） |
| Score measured tokens | **14469** |
| HTTP | gen **1** + score **1** |

## 费用（项目估价，非账单）

| 步骤 | prompt | completion | est_usd |
|------|-------:|-----------:|--------:|
| Generator max5 | 64614 | 997 | 0.01029 |
| Causal Scorer | （审计未回填 prompt/completion；est 基于测量） | — | 0.002711 |
| **合计** | | | **≈0.013001** |

请求最多 5 条，模型返回并接受 **5** 条（rejected=0）。

## 排序（观察先验，非因果证明）

权重：internal_causal_link 30% / anchor_causal_bridge 30% / joint_causal_gain 25% / factual_support 15%。

| 序 | ID | prior | I/A/J/F | 关系类型 |
|---:|----|------:|---------|----------|
| 1 | H1 | 0.50 | 2/2/2/2 | narrative_association |
| 2 | H5 | 0.50 | 2/2/2/2 | state_transition |
| 3 | H2 | 0.2875 | 1/1/1/2 | causal_hypothesis |
| 4 | H3 | 0.2875 | 1/1/1/2 | narrative_association |
| 5 | H4 | 0.2875 | 1/1/1/2 | narrative_association |

`selected_for_video_observation`: H1 → H5 → H2 → H3 → H4。`planner_eligible` 全部 false。

**勿用本轮 prior 与旧五维总分做模型能力对比**（评分标准已变）。下面只谈候选本身的因果组合质量。

## 因果组合质量（重点）

### H1 — 点球犯规 → VAR 取消 → 拦截（prior 并列最高）
- **有可解释内核**：`event_000617`（2队踢1队造成点球犯规）与 `event_000622`（VAR 取消点球，replay）构成「接近得分被阻断、比分差仍在」的受阻状态，内部因果可读。
- **弱链/串接风险**：第三事件 `event_000635` notes 为 **2队拦截1队传球**，与摘要「攻势延续」冲突；关系类型本身是 `narrative_association`。Scorer 已写明 opposing-team interception 削弱续攻读法。
- 结论：多事件里 **前两段有真实机制，末段像时间邻近硬接**，不是干净的三事件因果链。

### H5 — 三次连续拦截（prior 并列最高）
- 时间上紧贴扳平窗口（6403→6410s），`state_transition` 声称球权转换导向扳平进攻。
- notes 球队：**1队 → 2队 → 1队** 交替，并非「主角队连续夺回球权」。Scorer 明确指出标签与叙事不完全匹配。
- 结论：更像 **扳平前球权拉锯的时间簇**，因果增益有限；可观察，但不宜当成已证实的组织起点。

### H2 — 换人后角球/射门（低分）
- 支持列表时序 **非单调**：角球 `5527s` 列在换人 `5557/5561s` 之后，但实际更早。
- 换人 notes 为 **2队换人**，角球/射门为 **1队** —— 典型跨队硬串。Scorer I/A/J=1。
- 结论：**不相关事件串联** 特征明显。

### H3 — 连续带球突破「攻防拉锯」（低分）
- 四条全是 **1队 Dribble_past**，没有引用防守拦截事件；摘要写「突破与拦截交替」与事实不符。
- 关系类型 `narrative_association`；属于同类事件节奏拼接，**几乎无多事件因果结构**。

### H4 — 黄牌后任意球/角球（低分）
- 黄牌对象为 2队7号，随后 1队任意球/角球：若黄牌来自对1队犯规，任意球尚可弱关联；角球再接上则偏松。
- Scorer：定位球并非由黄牌本身引起。偏 **弱叙事联想**。

## 总判

- 本轮 **没有出现强、可单独立住的多事件因果组合**。
- 相对较好的是 H1 的「点球→VAR 取消」双事件核心；一旦并入 635 即滑向邻近串接。
- H2/H3 清晰暴露 Generator 仍会产出 **跨队或同型事件堆叠** 的候选；四维 Scorer 能把它们压到 I/A/J=1，但不会删除。
- 与上一轮对照时，请比较 **事件组合是否更像真实因果/状态演化**，不要比较总分数字。

完整 raw / ranking / audit：`docs/artifacts_scheme_a_causal4_run_20261116/`。
