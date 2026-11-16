# Story-First V2 P2：1× Vision 事件核验（2026-11-16）

基线报告 commit：`21acf592f381eb53ebbccd394241841522fee5e8`  
代码：`da8122663d4e76e3d457fe45b22dd0cc591fc806`  
产物：`/tmp/lpy1_story_first_v2_p2_vision1_20261116/`  
授权：**最多 1 次 Vision HTTP**（实际 **1**）

未重跑 Generator / Causal Scorer / Planner；未改正式 EDL。

## 1. 回归

`test_v3a_story_first_closed_loop.py` + `test_v3a_continuous_broadcast_phase.py`：**26 passed**

## 2. Vision 审计（唯一付费调用）

| 字段 | 值 |
|------|----|
| model | **Qwen3.7-Plus** |
| HTTP | **1 / 1** |
| prompt_tokens | 11061 |
| completion_tokens | 233 |
| finish_reason | **stop**（未截断） |
| est_cost_usd | **0.001799** |
| http_ok | true |
| 输入 | 复用 H5 预备 5 帧 + `review_input.json`（仅事件核验 schema） |

原始响应：`artifacts/.../source_review/review_response.txt`

## 3. 三事件视觉核验（可审计）

| 事件 | 状态 | 引用帧 | 模型理由（摘要） |
|------|------|--------|------------------|
| event_000634 | **UNCERTAIN** | f2 @6403.84 | 球员接近，未见明确抢断/触球 |
| event_000635 | **SUPPORTED** | f3 @6405.04 | 红衣球员可见争抢并断白衣球 |
| event_000636 | **UNCERTAIN** | f4 @6410.08 | 球员分离移动，无进行中的传球拦截 |

说明：模型将红衣标为 Team 2、白衣为 Team 1；与原子 notes「1队/2队」的主角映射需人工对齐，本轮**不**据此改标注或门禁。未做因果关系/剪辑适配判断。

非 SUPPORTED 反馈已写入 `event_feedback.json`。

## 4. FIRST_LIVE（独立、真实、可追溯）

复用历史本地包（paid round1 / da81226 预检），**未重建、未伪造**：

| 项 | 结果 |
|----|------|
| window key | `a66147f7…\|6395.810:6418.070` |
| binding | `FRAME_BOUND_VALID`（校验通过） |
| timeline | `binding_only_no_timeline_proof` / outcome **UNKNOWN** |
| first_live_verified | **false** |
| 入账为 FIRST_LIVE_VERIFIED | **否**（未达现有认证条件） |

### 缺口与最小补证（不改门禁）

1. 需要针对该 SHA + `[6395.81,6418.07]` 的**独立连续播出时间轴审查**，`outcome=FIRST_LIVE_VERIFIED`，且满足 `validate_first_live_evidence_record(..., allow_non_goal_action=True)` 的正向相位证据（非仅帧绑定）。  
2. 原子 `broadcast_phase=LIVE` / 粗窗口 `[6400.9,6412.5]` **不能**替代首次直播认证。  
3. **禁止**手改 JSON 翻转 `first_live_verified`。

## 5. 门禁结果

- `status`: **NEEDS_REVISION**
- 阻断：634/636 `UNCERTAIN` + FIRST_LIVE `event_pts_only_pending_first_live_attestation`
- **`intents=[]`** → 不进入正式 EDL / 不进 P3 试剪

## 6. 结论

- 真实 Vision 完整且未截断；三事件均有独立可审计结果。  
- FIRST_LIVE 仍不足；P3 未就绪。  
- 下一步最小动作：补独立 FIRST_LIVE 认证；若要坚持 H5，可考虑对 634/636 增加更密事件时刻帧后再核验（需新授权）。
