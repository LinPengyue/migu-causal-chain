# V3-A Stage-2 Evaluation（离线证据提案 Planner）

**开发分支：** `story-va-v3-a`  
**评估提交基线（推送前 HEAD）：** `7c1ab58`（本报告提交后以 push SHA 为准）  
**冻结基线（只读、未改）：** `story-va-v3-r-frozen-20261103` → `2d1ec9c`  
**付费 API：** 0（默认 `rule_fallback`，未传 `--enable-real-llm`）  
**自动改 EDL / 重渲：** **禁止且未发生**（`edl_modified=false`，输出写在 phase5 **外**）  
**render_ready / 正式授权：** false / **NOT_AUTHORIZED**（全场）  
**说明：** Stage-2 只产出证据搜索提案；不验证进球、不应用修订。

---

## 1. 测试执行结果

命令：

```bash
PYTHONPATH=10.27scasual_chain/algo \
python -m unittest discover \
  -s 10.27scasual_chain/tests \
  -p 'test_v3a_*.py' -v
```

| 结果 | 值 |
|------|----|
| 通过 | **21 / 21** |
| Stage-1 `test_v3a_quality_audit` | 10 / 10 |
| Stage-2 `test_v3a_planner_stage2` | 11 / 11 |
| 失败 | 0 |
| 本轮改码 | **无**（仅跑验证 + 写本报告） |

Stage-2 单测覆盖：坏 audit 拒收、跨场泄漏拒收、空 LLM 选择不能跳过 P0、FR 缺球→有界搜索而非 Goal 标签、LLM 仅可重排已有 ID、捏造时间/任务拒收、无锚点拒造 media time、A/B/C 结构 OK 不对 P2 freeze 出修订、UNKNOWN 不能变 edit、CLI 默认无远程且不改输入。

---

## 2. 四场离线 Planner 输入 / 输出

| 场 | `--phase5-dir` | Stage-1 audit | `--out` |
|----|----------------|---------------|---------|
| A | `.../closed_loop_A_uae_oman/04_phase5_p1_polish` | 同目录 `v3a_quality_audit.json` | `.../closed_loop_A_uae_oman/v3a_stage2_planner_proposal.json` |
| B | `.../closed_loop_B_osasuna_celta/04_phase5_p1_polish` | 同目录 | `.../closed_loop_B_osasuna_celta/v3a_stage2_planner_proposal.json` |
| C | `.../closed_loop_C_croatia_canada/04_phase5` | 同目录 | `.../closed_loop_C_croatia_canada/v3a_stage2_planner_proposal.json` |
| FR | `.../closed_loop_FR_france_australia_zeroshot/04_phase5` | 同目录 | `.../closed_loop_FR_france_australia_zeroshot/v3a_stage2_planner_proposal.json` |

约束：proposal **不写进** 冻结 phase5 目录；`source_sha256` 与现场 `candidate_edl.json` 校验一致（四场均 **match**）。

| 场 | mode | candidates | selected | edl_modified | render_ready | requires_stage3 | real_requests |
|----|------|------------|----------|--------------|--------------|-----------------|---------------|
| A | rule_fallback | 0 | **0** | false | false | false | 0 |
| B | rule_fallback | 0 | **0** | false | false | false | 0 |
| C | rule_fallback | 0 | **0** | false | false | false | 0 |
| FR | rule_fallback | 1 | **1** | false | false | **true** | 0 |

---

## 3. 四场任务列表

### 3.1 A / B / C（保护性）

- `revision_requests`：**空** → Planner 候选 / 选中任务均为 **0**。
- Stage-1 仅有 **P2** `possible_image_anomaly`（片头/片尾 freeze 筛查，与标题卡一致）→ **未**进入候选，**未**触发修订提案。
- 关键进球 EDL 段保持不变（例）：
  - A: `seg_opponent_opening_goal_action` 1325–1347；equalizer 6437–6459；go_ahead 6831–6853
  - B: opening 3121–3143；equalizer 5645–5667；go_ahead 6779–6801
  - C: opening 968–990；equalizer 3053–3075；go_ahead 3511–3533（+ lead_extend）
- `unverified` 仍为 `[live_vs_replay_visual_truth, VLM_semantics, shot_event_grounding]`；未发现的视觉问题继续 **UNKNOWN**，未伪造证据。

### 3.2 FR（重点）

| 字段 | 值 |
|------|----|
| task_id | `issue_000` |
| issue_kind / target | **`missing_story_element` / `opponent_opening`** |
| severity | P0 |
| repair_intent | `add_missing_role_after_evidence_verification` |
| required_role | `opponent_opening_goal_action` |
| may_edit_edl | **false** |
| evidence_status | **UNVERIFIED** |
| anchor | T01 `behind_start` **score_anchor_sec=1535.65**（score `0:1`） |
| anchor_kind | **`score_path_confirmation_NOT_goal_action`** |
| evidence_refs | 仅 `T01_selected_arc_score_node` / `SOURCE_ANCHOR_ONLY` |
| search_profile | `score_anchored_goal_action_search` |
| target_segment_id | null（尚未绑定现有 EDL 段） |

**未出现：** `Goal@1351`、`1351.642`、`atom_fill_0004_Goal_1351642` 作为证据或候选进球声明。

---

## 4. 法国场搜索窗口

源片时长（enrich `video.duration_sec`）：**7305.555 s**  
推导：`LOOKBACK_SEC=180` + `AFTER_SCORE_SEC=15`，自锚点 1535.65 切 ≤30s 窗，上限 8 窗。

| # | start | end | span |
|---|-------|-----|------|
| 1 | 1355.65 | 1385.65 | 30 |
| 2 | 1385.65 | 1415.65 | 30 |
| 3 | 1415.65 | 1445.65 | 30 |
| 4 | 1445.65 | 1475.65 | 30 |
| 5 | 1475.65 | 1505.65 | 30 |
| 6 | 1505.65 | 1535.65 | 30 |
| 7 | 1535.65 | 1550.65 | 15 |

| 检查项 | 结果 |
|--------|------|
| 区间 ⊆ [0, 7305.555] | **PASS**（全局 [1355.65, 1550.65]） |
| 是否采用 Goal@1351 为真实进球证据 | **否**（证据源仅为比分确认锚 1535.65） |
| 首窗时间是否与否定原子时间邻近 | 是（lookback 边缘落到 ~1355，与已否 Goal@1351≈1351 **时间邻域重叠属预期**）；Stage-3 必须独立视觉核验，不得把旧 LIVE 原子当 ground truth |
| edl_modified / render_ready | **false / false** |

---

## 5. 误报 / 漏报与边界

| 项 | 判定 |
|----|------|
| FR P0 `missing_story_element:opponent_opening` | **命中正确**（与 Stage-1 / 人工 QC 一致） |
| A/B/C 对标题卡 freeze 出修订 | **无误报**（P2 不进候选） |
| A/B/C 改已正确关键进球 EDL | **未发生**（0 任务 + EDL sha 不变） |
| 把 Goal@1351 写进提案证据 | **无误报** |
| 搜索窗落在片源外 | **无** |
| 视觉真伪 / LIVE vs REPLAY | 仍 **UNKNOWN**（本阶段不调 VLM、不抽帧复验） |
| Stage-2「找到进球」声明 | **无**（`PROPOSAL_ONLY` / `UNVERIFIED`） |
| 漏报风险 | 若真实破门远早于 score 确认超过 180s lookback，当前有界搜索可能不够 → 记 **产品边界 / 待 Stage-3 评估**，非本阶段假成功 |

---

## 6. 是否可进入下一步

| 门槛 | 状态 |
|------|------|
| 全量 `test_v3a_*.py` 绿 | **是** |
| 离线四场 Planner 可跑且不改冻结产物 | **是** |
| FR 产出有界、有来源的 P0 搜索任务 | **是** |
| 明确拒绝 Goal@1351 作进球证据 | **是** |
| A/B/C 保护（无无必要修订） | **是** |
| 付费 API / 自动 EDL 应用 / 重渲 | **未使用** |
| 可进入 **Stage-3（视频证据获取与人工/VLM 核验）** | **可以（仅 FR 的 issue_000；A/B/C 无 Stage-3 必做任务）** |
| 可自动改 EDL / 宣称 render_ready | **否** |

**结论：** Stage-2 离线 Planner 验证通过，可进入下一步 **有界视频证据检索（Stage-3）**，且仅针对法国场 `opponent_opening` 提案；在证据独立确认前，**禁止**应用 EDL 修订或放行成片。

---

## 7. 复现命令摘要

```bash
cd /data2/lpy1/worktrees/migu-story-va-v3-a
PYTHONPATH=10.27scasual_chain/algo \
python -m unittest discover -s 10.27scasual_chain/tests -p 'test_v3a_*.py' -v

ROOT=/data2/lpy1/_story_va_outputs/v3/plan2
PYTHONPATH=10.27scasual_chain/algo \
python -m story_video_agent_v3.planner_stage2 \
  --phase5-dir "$ROOT/closed_loop_FR_france_australia_zeroshot/04_phase5" \
  --out "$ROOT/closed_loop_FR_france_australia_zeroshot/v3a_stage2_planner_proposal.json"
# A/B 使用 04_phase5_p1_polish；C 使用 04_phase5。勿传 --enable-real-llm。
```
