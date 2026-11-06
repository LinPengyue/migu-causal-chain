# V3-A 阿曼场单轮真实 Agent 闭环 — 零付费就绪报告

**Worktree：** `/data2/lpy1/worktrees/migu-v3a-handoff-A`  
**Branch：** `story-va-v3a-composer-handoff-A`（已推送 origin；未合主分支）  
**基线 handoff commit：** `35c21d98fa5deb1e38dc2c74420992a36391adc5`  
**本就绪改动：** 见本提交（one-round budget + preflight）  
**付费 API：** **未调用**

---

## 1. 同步与检查

| 项 | 结果 |
|----|------|
| HEAD @ 推送前 | `35c21d9` handoff 已 `git push -u origin story-va-v3a-composer-handoff-A` |
| 冻结 V1/V2/V3-R | 未改 |
| 历史实验产物 | 只读 |
| `composer_to_v3a_handoff_audit.md` | 与 `composer_evidence_handoff.py` / Planner 映射一致（KEEP/INSPECT/REPAIR/UNRESOLVED） |
| 回归 | handoff 7 + self_revise 6 + one_round readiness 5 → OK |

---

## 2. 实验设计（隔离单轮，尚未付费执行）

**目标段：** `seg_opponent_opening_goal_action`  
**输入 Phase5：** fresh E2E `05_v3a/_baseline_phase5`（`prefer_p1_polish=false`）  
**历史观察：** `A_vlm_smoke_20261105_210200/observation.json`（校验视频 SHA、PTS、frame_id 引用；标记 `historical_reuse`，**不计新 HTTP**，**不认证 FIRST_LIVE**）

### 预算硬限制（代码强制）

| 限制 | 值 |
|------|----|
| `max_rounds` | 1 |
| `max_calls`（HTTP attempts） | 3（Planner≤1 + VLM≤1 + Verifier≤1） |
| `max_retries` | **0**（失败即停，无自动重试） |
| VLM tools | ≤1，且必须命中 opening 锚点 |
| windows / followups | 1 / **0** |
| `max_cost_usd` 估费 | 0.05 |
| 自动渲染 / 改冻结 EDL | 否 |

实现入口：`--one-round-opening-goal` + `--seed-observations`（`self_revise_agent.run_self_revise` / CLI）。

### 证据缺口（为何仍可能需要 1 次新 VLM）

历史 Qwen 观察：`observed_shot=false`，可见事后/网内与比分 0-1。  
预检 disposition = **INSPECT**，缺口 `missing_goal_action_in_keyframes`，目标窗 **[1325.123, 1347.123]**。  
若 Planner 选 KEEP（仅复用历史观察）→ **0 次 VLM HTTP**；仅 INSPECT 且工具通过焦点过滤时才允许 1 次新观察。

---

## 3. 零付费预检结果

**预检目录：** `/data2/lpy1/_story_va_outputs/v3/plan2/A_one_round_preflight_20261106_124726`  
**状态：** `READY_FOR_AUTHORIZED_ONE_ROUND`（`real_http_executed=false`）

| 检查 | 结果 |
|------|------|
| Planner 可见完整 Composer handoff | ✓ |
| KEEP / INSPECT 决策可映射现有 schema | ✓ |
| VLM 仅在 INSPECT+缺口时触发；非焦点工具被过滤 | ✓ |
| KEEP 无新证据不改 EDL 窗 | ✓ |
| 历史观察非新调用、非 FIRST_LIVE | ✓ |
| HTTP retries=0、max_calls=3 | ✓ |
| Verifier 路径带 baseline vs candidate（`decide_accept` 无证据不接受） | ✓ |
| 输出目录隔离 / 无自动渲染 | ✓ |

脚本：

```bash
cd /data2/lpy1/worktrees/migu-v3a-handoff-A
export PYTHONPATH="$PWD/10.27scasual_chain/algo"
python 10.27scasual_chain/scripts/preflight_v3a_A_one_round.py \
  --out-dir "/data2/lpy1/_story_va_outputs/v3/plan2/A_one_round_preflight_NEW"
```

---

## 4. 授权后建议执行命令（当前不要跑）

```bash
cd /data2/lpy1/worktrees/migu-v3a-handoff-A
export PYTHONPATH="$PWD/10.27scasual_chain/algo"
# source API env safely; export STORY_VLM_MODEL; STORY_API_MAX_COMPLETION_TOKENS=2048
OUT="/data2/lpy1/_story_va_outputs/v3/plan2/A_one_round_opening_$(date +%Y%m%d_%H%M%S)"
VIDEO="/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4"
python -m story_video_agent_v3.self_revise_agent \
  --phase5-dir "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/fresh_e2e_A_real_20261105_183136/05_v3a/_baseline_phase5" \
  --out-dir "$OUT" \
  --video "$VIDEO" \
  --no-prefer-p1-polish \
  --max-rounds 1 --max-calls 3 --max-cost-usd 0.05 \
  --max-completion-tokens 2048 --max-retries 0 \
  --one-round-opening-goal \
  --seed-observations "/data2/lpy1/_story_va_outputs/v3/plan2/A_vlm_smoke_20261105_210200/observation.json" \
  --enable-real-api --i-approve-budget
```

失败后**禁止**自动重跑。

---

## 5. 剩余风险

1. Planner 单次超时（无重试）→ 规则降级；不得当作真实多模态成功。  
2. 新 VLM 调用即使成功也不等于 `FIRST_LIVE_VERIFIED`。  
3. Verifier 通过 ≠ 成片可发布（`render_ready` 保持 false）。  
4. 必须使用独立空 `OUT`；勿写入冻结 phase5 / 历史 polish。

**结论：** 零付费预检通过，具备授权后执行单轮真实闭环的条件；**本次已停止，未发起付费调用。**
