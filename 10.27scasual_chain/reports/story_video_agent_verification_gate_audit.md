# 核验门禁修复审计（Phase 3B/4A）

**分支**: `story-va-phase2c`  
**范围**: 仅 `10.27scasual_chain/algo/story_video_agent`  
**付费 API**: 未执行

## 1. Phase 4A 远程同步

下列本地提交已 **普通 push** 至 `origin/story-va-phase2c`（无 force-push、未动 `main`）：

| Commit | 说明 |
|--------|------|
| `fc36c41` | Phase 4A multimodal shot search（gated real API） |
| `f7b7e79` | Fix label extraction |
| `67ad782` | Clarify go-ahead mock labels in report |

## 2. 门禁缺陷与修复

### 原问题

`sanitize_plan_trust` 曾在看到 JSON 中 `granted_by == internal_verification_pipeline` 时**恢复** `pipeline_verified`。攻击者只需写入该字符串即可伪造成片资格。

### 修复要点（`internal_verification.py`）

1. **外部字段一律不可信**：`granted_by` / `pipeline_verified` / `time_pipeline_verified` / `render_eligibility=render_ready` / `grant_record_id` 等从外部 JSON 剥离，**绝不**因字符串匹配恢复授权。
2. **三轴分离**：
   - `media_time`：界内 ⇒ `ok_for_preview_cut`（可裁切）；`grants_render=false`
   - `semantic`：须 `attest_semantic_result` 签发 MAC 记录；`passed|failed|unresolved`
   - `render_grant`：须 media_ok **且** semantic_passed，并写入带 HMAC 的 `internal_grant_ledger`
3. **重载再验证**：`revalidate_plan_grants(plan, media)` 用 ledger MAC + 当前 `MediaInfo` 指纹 + 时间窗绑定重验；失败则不成片。
4. **final 渲染**：`video_renderer` 经 `revalidate_plan_grants`，禁止降级 preview。

## 3. 克罗地亚扳平窗口调整依据（诚实说明）

| 项 | 结论 |
|----|------|
| v1 窗 | 3061.903–3073.903s（Phase 3A.1 候选 EDL） |
| v2 窗 | 3059.903–3071.903s |
| **产生原因** | **Mock VLM** 对 seed 窗返回 `goal`/`shot`（conf≈0.55）后，**规则策略** `shrink/accept` 微调中心窗；**不是**真实视觉模型观察 |
| 抽帧 | 来自真实比赛文件（FFmpeg），但理解结果为 mock |
| 准确率 | **不得宣称**已优化进球识别准确率 |

go_ahead：仍无可信进球证据 → `unresolved` / blocked 占位；`final` 硬拒绝。

## 4. 负例测试（`test_verification_gates.py`）

- 伪造 `granted_by=internal_verification_pipeline` → 剥离、不成片
- 伪造 ledger MAC → revalidate 拒绝
- 伪造视觉 `pipeline_verified` → 不自动 semantic pass / render
- 时间合法但语义 `failed`（错误进球）→ 不 promote
- 仅界内无语义 → 可记录 cuttable，不成片
- 窗口篡改 → grant 失效
- 克罗地亚 plan：go_ahead 保持非 render_ready；`final` Raise

## 5. 回归

```text
PYTHONPATH=algo python -m unittest \
  story_video_agent.test_verification_gates \
  story_video_agent.test_phase3b \
  story_video_agent.test_phase3a1 \
  story_video_agent.test_phase4a.Phase4AGateTests \
  ...
```

Phase 4A 多轮搜索与 v2 preview 能力保留；默认仍 Mock，不计费。

## 6. 下一步（需用户明确授权）

1. 配置 Key + `STORY_PHASE4A_REAL=1` + caps  
2. 小规模 **VLM-only** 联调  
3. 再跑 **Planner+VLM** 多轮搜索  

未经明确授权不得计费。
