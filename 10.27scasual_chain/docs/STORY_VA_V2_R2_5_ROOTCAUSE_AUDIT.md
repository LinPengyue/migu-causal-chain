# Story VA V2 R2.5 — V1/V2 根因审计报告

## 媒体时间轴

V1 与 V2 共用同一原始 MP4：`/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4`（8034.703s）。**SAME_MEDIA_TIMELINE**。

V1 phase5 仅作离线诊断，未进入 V2 推理输入。

## 四粒进球对照

| 比分 | V1 动作 | V1 记分牌 | V2 result | Δ(V2−V1) | 归因 |
|------|---------|-----------|-----------|----------|------|
| 0:1 | 980.137 | 1079.06 | 982.063 | +1.9s | 双方接近直播开球 |
| 1:1 | 3065.903 | 3145.98 | 3107.72 | **+41.8s** | V1=首次直播；V2 偏晚（疑似回放/第二机位） |
| 2:1 | 3523.574 | 3697.35 | 3566.64 | **+43.1s** | 同上 |
| 3:1 | 6317.199 | **6408.70** | **6461.08** | **+143.9s** | V2 在真实记分牌确认之后 → **确定回放** |

对照素材：`frames/`、`clips/`（本目录上一级）。

## Goal Recovery 根因（主因）

`sanitize_raw_event` 只读 `attributes.Score_Recognition`。  
`event_000118`（Foul LIVE，**6408.70**，首个 3:1）只在 `scores.score_recognition` 有比分 → 被丢弃。  
轨迹错误地把 2:1→3:1 锚到 **`event_000119` Substitution REPLAY @6479.08**。  
`refine_tail` 搜 6434–6479，回收到 6457/6461 的射门入网（回放邻域），并错误 `verified`。

次因：refine_tail 近确认偏置（1:1/2:1 +~42s）；shot+net 标签拼凑；cross-row stitch；final_mp4 `late_only_mixed` 假阳性。

## 验收假阳性

`croatia_r2_5_fix_20261030_094019` 报告 `all_five_goals_visual_pass=true`，但 ke_3/ke_4 的 `live_or_replay_final=mixed_or_ambiguous` 仍 pass。

## 已做最小修复

1. Adapter 回退读取 `scores.score_recognition` → 3:1 确认回到 **6408.70 LIVE**
2. 比分轨迹优先 LIVE 确认（4:1 从 REPLAY 154 改到 LIVE 155）
3. 发射门禁：`result` 不得晚于确认；拒绝 mixed
4. 禁止跨观察 shot/net 拼接
5. final MP4：任意 mixed/replay 失败；同一 live probe 需同时有 shot+net；删除 late_only_mixed 放行
6. 负例测试：有射门入网但是回放 → 判定 replay，不得验收通过

`render_ready=false`。未改 V1 / 8.31 events，未重跑付费 Goal Recovery / Story Planner。
