# B场 set_piece_breakthrough 漏检根因审计（ST-089 离线对照）

- **HEAD**: `23b4f60`
- **范围**: 仅 B 奥萨苏纳VS塞尔塔 / `set_piece_breakthrough`
- **约束**: 零付费、只读、复用已有 V3-R 产物、不改算法、不重跑、FanEdit ST-089 仅离线诊断

## 结论

漏检发生在 **R2a 语义抽取**：`corner_coop_goal` 链上的进球前角球是 `causal_atom_fill` 注入事件，**无 notes/attributes/球队**，无法写入 `set_piece_execution`。  
R2bc `relation_path` 因此 **0 起点** → R3 **0 故事**。  
8.31 短链与 atom 补齐本身已给出可连路径；不是 R3/Story Agent 问题，也不是 B 场特例逻辑错误。

## 链路摘要

| 阶段 | 状态 | 要点 |
|------|------|------|
| 8.31 | 有信号 | `corner_coop_goal` ×3（pred_0030/0053/0054） |
| atom 补充 | 半残缺 | 角球/射门/进球被 fill，但角球空标注 |
| R2a | 拒绝谓词 | fill 角球无 `set_piece_execution` |
| R2bc | 0 候选 | `_start` 返回 None |
| R3 | 0 故事 | 上游空输入 |

## 关键实际事件

1. `atom_fill_0070_Corner_kick_3130930` (t=3130.93) → `atom_fill_0072_Goal_3133968` (t=3133.97, team_1)  
2. `atom_fill_0114_Corner_kick_5655418` (t=5655.42) → `atom_fill_0116_Goal_5657621` (t=5657.62, team_2)

近邻人类任意球 `event_000555`（team_1, t=5585.63）距进球 ~72s > `max_span_sec=45`，且受益方不匹配，**不是**正确起点。

## 代码位置

- `semantic_normalization.py` L128–155：`set_piece_execution` 依赖可解析 `execution.team`
- `relation_story_patterns.py` L34–36 / L58–175：`_start` + `relation_candidates`
- `r2bc_patterns.py` L23–24：模板 `path("set_piece_execution")`

## 候选拒绝原因（分类）

1. **no_set_piece_execution_predicate** — 上述 2 个 fill 角球（主因）  
2. **span_exceeded / actor_mismatch** — `event_000555` 等错误近邻  
3. **no_valid_same_actor_path** — 其余 15 个已有谓词的人类定位球未连到同队进球

## 只读反事实

仅在内存为两枚 fill 角球注入与 `corner_coop_goal` 共现进球受益方一致的 `set_piece_execution.actor` 后，现有 `relation_candidates` **立即产出 2 条候选**（路径含 Shot 中间点，chain_ids 为 pred_0030/0053 等）。  
说明修复应落在**通用 actor 绑定/enrich 完整性**，禁止 B 场硬编码。

## 通用性

- FRA：人类角球带 notes+BallController → 2 候选（对照成功）  
- C fresh_general：0 候选（同类风险）  
- FanEdit `ST-089-723B1912`：plan 已标 `ZERO_CANDIDATE_ON_MATCHED_EXISTING_B_AUDIT_FIRST`；本轮未把金标段落输入推理

## 给后续修复设计的边界

- 可做：通用 fill-restart 球队绑定 / enrich 补全 / 在不放松核验的前提下利用链共现假设  
- 不可做：写入 ST-089 金标、B 场 event_id/时间硬编码、跳过 observation/verification、本轮付费重跑
