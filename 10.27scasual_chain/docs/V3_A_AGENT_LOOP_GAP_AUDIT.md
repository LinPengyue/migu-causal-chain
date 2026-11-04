# V3-A Agent 闭环缺口修复审计

**分支：** `story-va-v3-a`  
**基线提交：** `cbb16d1`  
**设计依据：** `docs/V3_A_AGREED_DESIGN_CONTRACT.md`  
**本轮付费 API：** **否**（仅合成回归；未发起新的真实 HTTP）  
**V3-R 冻结 / 原始 EDL·MP4：** **未改动**

---

## 1. 能力是否已实现

| 缺口 | 实现状态 | 说明 |
|------|----------|------|
| 证据绑定 + 局部 EDL 修订 | **已实现（代码）** | `authorize_bound_segment` / `build_bound_segment_from_observations`；`search_add`/`replace` 在通过独立门禁后写入工作副本；仍标 `first_live_status=NOT_VERIFIED`，禁止记分牌确认时间冒充进球动作，禁止 replay / `fact_verified` 过声称 |
| `decide_accept` 双路径 | **已实现（代码）** | `p0_repair`：P0 清零 + 证据绑定编辑；`quality_improvement`：无 P0、可核验覆盖/连贯改善或带 evidence_refs 的维度改善，且关键进球镜头未退化；模型自评单独不足 |
| 观察反馈与窗口调整 | **已实现（代码）** | 多窗观察 + `select_followup_windows` / `parse_next_search_request`；负例窗不可推断全场无球；自由时间戳 next_search 拒绝或吸附到可信窗；记录 `window_schedule_log` |
| 三维 Verifier + 502 重试 | **已实现（代码）** | `dimensions` 强制三维；`hard_vetoes`；`call_llm_verifier` 对 502/timeout/proxy 有限重试；失败不设 `rule_fallback_success` |

模块：`algo/story_video_agent_v3/self_revise_agent.py`  
测试：`tests/test_v3a_agent_loop_gaps.py`（+既有 `test_v3a_self_revise_agent.py`）

---

## 2. 是否通过测试

命令：

```bash
PYTHONPATH=10.27scasual_chain/algo \
python -m unittest discover -s 10.27scasual_chain/tests -p 'test_v3a_*.py' -v
```

| 套件 | 结果 |
|------|------|
| `test_v3a_agent_loop_gaps`（本轮新增） | **11/11 OK** |
| `test_v3a_self_revise_agent` | **6/6 OK** |
| `test_v3a_quality_audit` + `test_v3a_planner_stage2` | OK |
| `test_v3a_stage3_evidence` | 1 既有失败：`test_cannot_use_changed_phase5_files`（Stage-3 hash 门禁，与本轮 Agent 闭环改动无关） |

合成用例覆盖用户验收点：

1. FR 有真实 PTS+结构化 VLM 支持 → 可写入候选 opening EDL，P0 清零（**仍 NOT_VERIFIED**）  
2. FR 无可靠证据（0-0 / scoreboard_only）→ 仅 pending，P0 保留  
3. A/B/C 无 P0，删除无关镜头 + Verifier 带 evidence_refs → `quality_improvement` 可接受  
4. 错误建议（域外时间 / fact_verified 过声称 / replay）→ 拒绝绑定  
5. 负例首窗后 follow-up 切到不同可信窗（非机械重复）  
6. Verifier `ok=false` → `decide_accept` 拒绝，不冒充成功  

---

## 3. 是否发生真实 API 调用

**否。** 本轮未设置 `--enable-real-api` / `--i-approve-budget`，未 source 付费环境跑 Agent。  
历史真实调用记录仍保留在：  
`.../closed_loop_FR_france_australia_zeroshot/v3a_self_revise_fr_min_20261104_r3/`（属上一轮，非本轮）。

---

## 4. 是否产生真实 EDL 修订

| 范围 | 状态 |
|------|------|
| 冻结 Phase5 / V3-R 原始 `candidate_edl.json` | **未修改** |
| 合成测试中的工作副本 EDL | 仅内存/临时对象；证明绑定路径可写候选段 |
| 成片 MP4 重渲 | **未发生** |

---

## 5. 是否真正改善成片

**否。**  
代码闭环与合成回归 **不等于** 成片质量改善。在下一次小预算真实 API 联调（法国场）并完成：真实抽帧 → 绑定 → Verifier 成功 → 接受工作副本 →（可选）候选渲染对照之前，不得宣称故事视频质量已提升。

---

## 6. 建议的下一步（仍需显式额度授权）

1. 法国场小预算真实联调（建议 `max_rounds=2`，沿用成本上限）。  
2. 验证负例窗 1355–1385 后是否按日志切换后续可信窗。  
3. 仅当证据绑定 + Verifier 双路径接受后，再对照基线评估成片；A/B/C 随后。  

**禁止：** 把本审计中的「能力已实现 / 测试通过」写成「成片已改善」。
