# V3-P5 Goal Recovery → Stock V1 Replay Report

**Branch:** `story-va-v3-plan2`  
**Baseline:** `038d763`  
**Paid API:** **0**  
**Gold `*_causal.json` in generation:** **no** (offline compare only)  
**8.31 strip mutated:** **no**  
**`render_ready`:** **false**

Artifacts:
- B: `/data2/lpy1/_story_va_outputs/v3/plan2/p5_goal_recovery_B/`
- A: `/data2/lpy1/_story_va_outputs/v3/plan2/p5_goal_recovery_A/`

Code: `goal_recovery.py`, `p5_goal_recovery_cli.py`, outcome injection in `v1_causal_adapter.py`

---

## Verdict

**全场 Goal 候选已从 `Score_Recognition` 自动恢复；在首次 LIVE 证据（P3/P4 + G2.2 packs）支撑下，stock V1 的关键进球节点与 `*_goal_action` 时间窗从 missing → 有真实媒体窗。**

| Match | 单球增量候选 | 有 `goal_action_sec` | V1 故事进球 BEFORE→AFTER | HUMAN 对照进球 | Compose `*_goal_action` PTS |
|-------|-------------|----------------------|---------------------------|----------------|-----------------------------|
| B | **5**（未写死） | **4** / 5 | **0 → 3** | 3 | **3/3 有 PTS**（BEFORE 全 null） |
| A | **3** | **3** / 3 | **0 → 3** | 3 | **3/3 有 PTS**（BEFORE 全 null） |

记分牌确认时间 **从未**写入 `goal_action_sec`。V3 最终 EDL 视图已剔除 `*_replay_supplement`；本阶段仍 **`render_ready=false`**。

---

## 1. Goal 候选恢复（比分增量）

算法：扫描交付 `events.json` 的 `Score_Recognition`，仅保留单球增量；记录球队侧、确认时刻、可能动作区间、附近 Shot/Save/Corner 等。数量由比分轨迹决定，不写死 3/5。

### B Osasuna–Celta

| # | 比分 | 确认秒 | `goal_action_sec` | 区间 / 来源 | 验证状态 |
|---|------|--------|-------------------|-------------|----------|
| 0 | 0-0→0-1 | 2018.45 | **1954.24** | nearby LIVE `Dribble_past` | `provisional_from_nearby_event`（弱） |
| 1 | 0-1→1-1 | 2660.82 | **null** | 无 Shot/LIVE overlay | `unresolved_goal_action` |
| 2 | 1-1→2-1 | 3199.66 | **3133.5** | **P3/P4 LIVE 3132–3146** | `possible_first_live_video_supported` |
| 3 | 2-1→2-2 | 5712.01 | **5630.64** | G2.2 equalizer first-live pack | `unresolved`（候选未视频终验） |
| 4 | 2-2→2-3 | 6881.94 | **6800.24** | G2.2 go_ahead first-live pack | `unresolved` |

### A UAE–Oman

| # | 比分 | 确认秒 | `goal_action_sec` | 来源 | 验证状态 |
|---|------|--------|-------------------|------|----------|
| 0 | 0-0→0-1 | 1410.43 | **1315.08** | G2.2 opening pack | `unresolved` |
| 1 | 0-1→1-1 | 6535.62 | **6472.96** | G2.2 equalizer pack | `unresolved` |
| 2 | 1-1→2-1 | 6957.12 | **6778.15** | G2.2 go_ahead（窗口末端落入 V1 匹配窗） | `unresolved` |

---

## 2. 真实动作时间（B 3132–3146 流程验证）

B 1-1→2-1：
- 确认 **3199.66** ≠ 动作  
- P3/P4：首次 LIVE **3132–3146**，动作先验 **3133.5**  
- 板面视觉翻转约 **3140→3144**（庆祝/记分牌，不作 action）  
- 注入 V1 结果链后：铺垫进球 `t_sec=3133.5`；compose `opponent_opening_goal_action` **3121.5–3143.5**

---

## 3. 结果链构建（V3 适配层）

- 保留完整 8.31 predicted chains（special/danger/…）  
- **追加** `结果链`：终端 `进球` + 可选 8.31/nearby 前因；无前因则 **独立 Goal 终端**（不虚构因果）  
- `is_replay=false`（正式路径只注入 LIVE）  
- 人工 `*_causal.json` **未读入**生成

---

## 4. Stock V1 前后对照

### B

| | BEFORE（无 Goal 恢复） | AFTER | HUMAN（对照） |
|--|------------------------|-------|---------------|
| 故事进球数 | 0 | **3** | 3 |
| 进球秒 | — | 3133.5 / 5630.64 / 6800.24 | 3176.8(replay) / 5657.6 / 6843.9(replay) |
| `*_goal_action` | 全 **null** | **3121.5–3143.5 / 5618.6–5640.6 / 6788.2–6810.2** | 有 PTS（含 replay_supplement） |

叙事角色对齐：铺垫 / 转折 / 高潮 三个关键节点均恢复。自动链动作为 LIVE 先验；人工故事事件含回放时间戳，compose 另有 `*_replay_supplement`。

### A

| | BEFORE | AFTER | HUMAN |
|--|--------|-------|-------|
| 故事进球数 | 0 | **3** | 3 |
| 进球秒 | — | 1315.08 / 6472.96 / 6778.15 | 1337.1 / 6449.6 / 6843.1 |
| `*_goal_action` | 全 null | **1303–1325 / 6461–6483 / 6766–6788** | 有 PTS + replay supplements |

差异：A 反超动作窗偏早于人工 LIVE（约 6778 vs ~6831）；G2.2 候选仍标 `unresolved`，需后续视频核验，**不**用人工时间覆盖。

---

## 5. 回放排除

`compose_AFTER/v3_final_edl_replay_filtered.json`：
- 丢弃 `is_replay` / `*_replay_supplement`  
- B/A：`n_live_goal_action_with_pts=3`，`render_ready=false`  
- 未完成全量首次 LIVE / 无回放 QC 前不得成片

---

## 6. 仍需远程 VLM 的候选（本阶段未调用）

零付费证据不足、**不要**自动付费；若批准预算，优先：

1. **B 0-1→1-1 @2660.82** — `goal_action_sec=null`，附近无 Shot/G2.2  
2. **B 0-0→0-1** — 仅有弱 `Dribble_past@1954` 先验  
3. **A/B G2.2 标注 unresolved 的 equalizer/go_ahead** — 需 shot/net + live_or_replay 终验  
4. **A go_ahead** — 动作窗与确认差偏大，需确认是否首次 LIVE

---

## 复现

```bash
cd /data2/lpy1/worktrees/migu-story-va-v3-plan2
export PYTHONPATH=10.27scasual_chain/algo
python3 -m story_video_agent_v3.p5_goal_recovery_cli \
  --tag B_osasuna --b-opening-overlay --g22-tag B_osasuna_celta \
  --events … --strip … --human-causal-compare-only … --out-dir …
```
