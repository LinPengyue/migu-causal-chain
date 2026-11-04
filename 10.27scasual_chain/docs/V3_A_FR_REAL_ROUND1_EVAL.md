# V3-A 法国场真实 API 单轮联调（max_rounds=1）

**日期：** 2026-11-04  
**分支 / SHA：** `story-va-v3-a` @ `26916528add523d9507a31553073f587c5e6387b`（联调代码基线 `e1a21d2`）  
**冻结 V3-R：** 未修改（`04_phase5/candidate_edl.json` sha256 `96ec2e66…`；`story_qc.mp4` `756084bc…`）  
**输出目录：**  
`/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_FR_france_australia_zeroshot/v3a_self_revise_fr_real_20261104_r1/`  
**控制台：** `…/v3a_self_revise_fr_real_20261104_r1_console.log`

## 运行配置（未抬高上限）

| 项 | 值 |
|----|----|
| 开关 | `--enable-real-api --i-approve-budget` + `STORY_API_ENABLE=1` |
| max_rounds | **1** |
| max_calls | **8** |
| max_cost_usd | **1.0** |
| max_completion_tokens | **2048** |
| phase5 | `closed_loop_FR_france_australia_zeroshot/04_phase5` |
| video | `/mnt/data4/migu/2022年11月23日 法国vs澳大利亚.mp4` |
| predicted causal | `03_v1_adapt/predicted_causal_live_goals_only.json` |

费用上限充足完成本轮；**未**擅自提高上限，**未**另开付费对照。

---

## 1. 本轮是否完整执行？

**编排完整结束：是。** `workflow_completed=true`，`rounds_executed=1`，`abort_reason=null`。

| 状态 | 值 |
|------|-----|
| `degraded_execution_success` | **true**（规则轨 + 基线保留） |
| `multimodal_self_revision_success` | **false** |
| `accepted_any_revision` / `agent_contributed_improvement` | **false** |
| `render_ready` / `release_decision` | false / `NOT_AUTHORIZED` |
| 冻结 Phase5 被改？ | **否** |

**不等于**多模态自修订成功。单轮未改善 ≠ 方案失败；见下方卡点分解。

---

## 2. Planner 发现了什么？

`provider_mode=real`，模型 **DeepSeek-V4-Pro-0813**，诊断经校验保留 **5** 条：

1. **P0** 缺 `opponent_opening` 进球动作（记分牌不可顶替）  
2. **P1** 预测原子 `Goal@1351.642` 早于 Stage-2 首窗 1355.65，搜索可能漏检（**观察候选，非已证实 LIVE**）  
3. **P2** equalizer 视觉真值 / LIVE·回放未核验  
4. **P2** go-ahead 同上  
5. **P2** 3:1/4:1 延伸进球是否超出 selected_arc 需审视  

模型 **raw** 还发出了 4 个视频工具请求（含 `score_node:behind_start` 回溯窗），但见 §卡点。

---

## 3. VLM 找到了什么证据？

**本轮未执行真实 VLM。**  
`vlm_observations.json`：`observations=[]`，`any_real_ok=false`。  
原因：校验后 `video_tool_requests=[]`（模型用了非契约字段名 `tool_name` / offset 窗，未归一成可执行 `vlm_observe` + 绝对秒窗）。

---

## 4. Verifier 反馈？

| 轨 | 结果 |
|----|------|
| Rule | 仍跑；`rule_verification_status=FAILED`（基线缺 opening P0） |
| API | HTTP **real 成功 1 次**，但 completion 几乎全是 `reasoning_tokens=2048`，**可见 JSON 为空** → `EvidenceNormalizationError:empty VLM response`（误分类错误名，实质为空 Verifier 正文） |
| 语义 | `semantic_verification_status=NOT_EVALUATED`（**未**伪造通过 / 未打 0·100） |
| `decide_accept(loop)` | `accept=false`；reasons: `api_verifier_degraded_rule_track_active`, `no_evidence_bound_or_safe_edit` |
| `decide_release` | `release_eligible=false` |

---

## 5. EDL / MP4

| 项 | 结果 |
|----|------|
| 工作副本相对冻结 EDL | **未改**（sha 相同；`evidence_bound_count=0`，仅 `pending_evidence_slot`） |
| V3-A 候选 MP4 | **未生成**（无有效 EDL 修订，不触发渲染） |
| vs V3-R 成片改善 | **无** |

`revision_meta`：`search_add` → pending（无观测可绑定）；不安全 `trim` 被拒。

---

## 6. 卡点分解（单轮未改善归因）

| 阶段 | 状态 | 说明 |
|------|------|------|
| 模型判断（Planner） | **完成** | 真实诊断有价值（含 1351 搜索覆盖风险） |
| 证据搜索（VLM） | **卡住** | 工具 schema 未通过校验 → 0 次 vision HTTP |
| 候选修改（EDL bind） | **卡住** | intent 缺 `role`/`anchor_id`；无 PTS/VLM 门控通过 |
| Verifier 语义 | **卡住** | 有 HTTP，但输出被 thinking 占满，解析失败 → NOT_EVALUATED |
| 最终渲染 | **未进入** | 无 accepted 修订 |

---

## 7. 费用与三轮预估

### 本轮实测

| 指标 | 值 |
|------|-----|
| http_attempts / real_ok / real_failures | **2 / 2 / 0** |
| prompt / completion / total tokens | 5421 / 11447 / 16868 |
| **est_cost_usd_real** | **≈ $0.007681** |
| elapsed_sec_real | ≈ 156 s |
| by_role | 仅 **planner**（含 Verifier 复用 planner 角色的第 2 次调用）；**vision=0** |

分项估算：

| 调用 | 角色 | tokens | est USD |
|------|------|--------|---------|
| 1 Planner | planner | 12705 | ≈ 0.00614 |
| 2 Verifier | planner | 4163 | ≈ 0.00155 |

未触达 `max_calls=8` / `max_cost_usd=1.0`。

### 三轮成本粗估（本地单价，非账单）

- **按本轮结构外推（仍无 VLM）：** ≈ 3 × 0.0077 ≈ **$0.023**  
- **若后续轮次补上 1 次 VLM（参考 r3 ≈ $0.0017/次）+ Planner/Verifier：**  
  约 (0.0077 + 0.0017) × 3 ≈ **$0.028**，量级 **<$0.05 / 三轮**（远低于 $1.0 硬顶）  
- 若 Verifier 重试或窗更多，可按 **$0.05–0.15 / 三轮** 作保守上沿；仍建议保持现有硬上限。

---

## 8. 与上一轮 r3 对比

| | r3 | 本轮 r1 |
|--|----|---------|
| Planner | real | real |
| VLM | real（一窗 0-0） | **未调用**（schema 剥空） |
| Verifier | 代理 502 | HTTP 通但 **空正文** |
| EDL 接受 | 否 | 否 |
| 费用 | ≈ $0.0083 | ≈ $0.0077 |

---

## 9. 结论

1. **一轮编排与费用门禁跑通**；规则兜底与 `NOT_EVALUATED` 诚实。  
2. **尚无**证据绑定修订与成片改善。  
3. 下一轮优先（不在本授权内执行）：收紧 Planner schema 归一（tool/intent 字段别名 → 可执行 `vlm_observe`），并抑制 Verifier 纯 thinking 空输出；再开 `max_rounds≥2` 时再授权。
