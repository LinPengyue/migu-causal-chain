# Story-First V2 P2 预检（da81226 简化核验路径）

代码：`da8122663d4e76e3d457fe45b22dd0cc591fc806`  
复用运行：`e0c68ea` Planner 选择 `interval_01:H5`  
本轮产物：`/tmp/lpy1_story_first_v2_p2_da81226_preflight_20261116/`（不覆盖上轮）  
**付费 API：0**

## 1. 回归

Story-First 专项（含 closed_loop / scheme_a / adapter / poc / local_patterns / continuous_broadcast）：**75 passed**

## 2. H5 离线重绑

| 项 | 结果 |
|----|------|
| 选择 | `interval_01:H5` → `event_000634/635/636` |
| 窗口 | **`[6395.81, 6418.07]`**（与历史一致） |
| trial_id | `ab22f01929b5cb4f59e6badd`（同键） |
| known_replay_or_slowmo | 三者均为 false |

未重跑 Generator / Scorer / Planner。

## 3. 简化源核验输入（仅事件可见事实）

`da81226` 已去掉关系因果与 before/candidate/after 剪辑适配；核验只抽 **candidate** 窗内帧。

| 项 | 数值 |
|----|------|
| 帧数 | **5**（含三事件精确 PTS 帧 f2/f3/f4） |
| Prompt 文本 token | **~650**（ba38ef7 约 1451） |
| 样例紧凑响应 | **~102** tokens |
| 默认 completion 上限 | 1200（充足，length 风险很低） |

Fixture：三事件均可走 `SUPPORTED` 评估路径。

## 4. FIRST_LIVE

本地 `build_local_first_live_evidence_pack`：

| 项 | 状态 |
|----|------|
| binding | `FRAME_BOUND_VALID` |
| first_live_verified | **false** |
| frame_pack_cannot_certify_first_live | **true** |
| timeline | `binding_only` / outcome UNKNOWN |
| 原子 LIVE hits | 有；replay_hits=[] |
| 可进试剪 | **否** |

即使 fixture 把三事件标成 SUPPORTED，`review_story_first_trial` 仍返回 `NEEDS_REVISION`，唯一阻断：`event_pts_only_pending_first_live_attestation`；**intents=[]**。

## 5. P3 门禁

**未就绪。** 仍缺：

1. **一次真实源视频事件核验**（Vision，仅事件行；可复用本轮 `review_input` / 帧）
2. **独立 FIRST_LIVE 证据入账**（本地帧包不够）

两项都通过后才会生成 `search_add` 试剪意图；剪辑适配改由渲染后双视频 Verifier。

## 6. 建议的下一步授权（未执行）

- 最多 **1** 次 Vision HTTP，项目估价上限建议 **$0.05**
- 复用 H5 trial + 本目录帧；禁止 Gen/Score/Planner
- FIRST_LIVE 需另附独立证据目录或人工连续播出审查

停止于零付费预检。
