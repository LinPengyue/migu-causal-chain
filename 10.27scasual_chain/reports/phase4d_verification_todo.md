# Phase 4D — 两次进球独立核验待办

**Cursor 不得模拟独立审核通过。** 生产签发仅接受：

- `human_audited_review`
- `independent_verification_pipeline`

当前包状态：`pending_independent_human_review` · `auto_granted=false` · `render_ready=false`

## 扳平（入网≈3067s）

| 帧 | media_sec | 用途 |
|----|-----------|------|
| shot | 3066.0 | 射门出手 |
| ball_in_net | 3067.0 | 入网 |
| celebration | 3072.0 | 庆祝 |

核对：frame_id、约 PTS/media_sec、「直播」标签、非回放、进球动作与庆祝。  
分层：人工结论 / 程序检测 / 模型观察（4B 仅参考，不作事实）。

## 反超（入网≈3525s）

| 帧 | media_sec | 用途 |
|----|-----------|------|
| shot_flight | 3524.8 | 射门飞行 |
| ball_in_net | 3525.0 | 入网 |
| celebration | 3526.074 | 庆祝 |

## 程序侧已写入

`evaluate_semantic_from_observations` → **unresolved / observation_only**（永不自动 passed）。

人工审核须走现有授权机制后，方可 `attest_semantic_result(..., authority=human_audited_review|...)`。
