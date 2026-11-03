# V3-P6 Video Alignment & No-Replay Acceptance

**Branch:** `story-va-v3-plan2`  
**Baseline:** `8a27d79`  
**Paid API:** 0  
**`render_ready`:** **false**

Artifacts: `/data2/lpy1/_story_va_outputs/v3/plan2/p6_video_alignment/`

---

## Verdict

六个 P5 `*_goal_action` 均已从源 MP4 **精确裁剪**并导出前后文与 **UNVERIFIED** 故事预览。目视验收后：

| 可进正式 EDL（`live_verified` + 含进球过程 + 低回放风险） | **2 / 6** |
|---|---|
| `live_status_unknown`（待复核/重裁） | **4 / 6** |
| `replay_detected`（整段判定） | **0 / 6** |

**`is_replay=false` 仅因注入结果链 → 一律作废。** 本阶段改为三态：`live_verified` / `replay_detected` / `live_status_unknown`。

---

## 1. 可观看导出

### 六个故事进球 MP4（P5 原窗）

**B** `.../B/goal_action_clips/`
- `00_opponent_opening_goal_action_3121_3143.mp4`
- `01_equalizer_goal_action_5618_5640.mp4`
- `02_go_ahead_goal_action_6788_6810.mp4`

**A** `.../A/goal_action_clips/`
- `00_opponent_opening_goal_action_1303_1325.mp4`
- `01_equalizer_goal_action_6460_6482.mp4`
- `02_go_ahead_goal_action_6766_6788.mp4`

上下文：`*/context_clips/`；抽帧：`*/audit_frames/`。

### 故事预览（未验收）

- `B/B_osasuna_story_goal_preview_UNVERIFIED.mp4`
- `A/A_uae_oman_story_goal_preview_UNVERIFIED.mp4`  

标注 **UNVERIFIED_NOT_FINAL_NO_REPLAY_QC**，禁止当作正式无回放成片。

### 纠正 / 重裁候选

- **A 反超纠正（目视确认）:** `A/corrected/A_go_ahead_CORRECTED_live_6838_6855.mp4`  
- 其他重裁仍标 UNVERIFIED:  
  `B/corrected/B_equalizer_RETRIM_UNVERIFIED_5645_5675.mp4`  
  `B/corrected/B_go_ahead_RETRIM_UNVERIFIED_6778_6800.mp4`  
  `A/corrected/A_opening_RETRIM_UNVERIFIED_1325_1350.mp4`  
  `A/corrected/A_equalizer_RETRIM_UNVERIFIED_6440_6475.mp4`

---

## 2. 六球目视结论

| 场 | 角色 | P5 Goal PTS | P5 EDL | 目视动作 PTS | 建议 EDL | LIVE 状态 | 正式 EDL |
|----|------|-------------|--------|--------------|----------|-----------|----------|
| B | 铺垫开场落后相关进球 | 3133.5 | 3121.5–3143.5 | **3133.5** | 3121.5–3143.5 | **live_verified** | **是** |
| B | 扳平 | 5630.64 | 5618.6–5640.6 | 未定位净过程 | 5645–5675* | live_status_unknown | 否（偏早，角球前） |
| B | 反超 | 6800.24 | 6788–6810 | ~6785 | 6778–6800* | live_status_unknown | 否（偏晚，多为庆祝） |
| A | 开场失球 | 1315.08 | 1303–1325 | 未确认 | 1325–1350* | live_status_unknown | 否（窗内仍 0-0 走动/混战） |
| A | 扳平 | 6472.96 | 6461–6483 | ~6465 | 6440–6475* | live_status_unknown | 否（窗内多为庆祝图） |
| A | 反超 | **6778.15** | 6766–6788 | **~6843** | **6838–6855** | **live_verified（纠正后）** | **纠正片段是** |

\* 重裁仅供人工复核，未宣称 live_verified。

完整 JSON：`p6_video_alignment/visual_audit.json`。

---

## 3. A 反超重点排查（P5 6778.15）

**结论：P5 自动窗定位错误（约早 65s），不是首次进球 LIVE。**

| PTS | 板面 | 画面 |
|-----|------|------|
| 6760–6788（P5） | **1-1** | 阿曼球员懊恼特写 / 非 UAE 破门 |
| 6831–6840 | 1-1 | LIVE 进攻组织 |
| **~6843** | 板面仍 1-1（滞后） | **球向球门网 / 入网过程 LIVE** |
| ~6848 | **2-1** | 庆祝开始 |
| ~6890+ | 2-1 | 疑似动作重放角度 |
| 6957 | 2-1 | 换人（Score_Recognition 确认点） |

未复制人工 V1 时间；纠正窗 **6838–6855** 来自记分牌滞后 + 入网/庆祝边界目视。人工对照窗 6831–6853 与纠正窗接近，属独立复核重合。

---

## 4. LIVE 状态策略纠正

| 旧（错误） | 新 |
|------------|----|
| 注入结果链 ⇒ `is_replay=false` | 无效 |
| — | `live_verified`：目视确认首次 LIVE 且区间含进球过程、未见回放包装 |
| — | `replay_detected`：明确慢动作/多机位重播占主导 |
| — | `live_status_unknown`：证据不足或窗偏早/偏晚 |

正式 EDL 仅当：`live_verified` ∧ 含进球过程 ∧ 剪辑区间无回放。

---

## 5. 自动 V3 vs 人工 V1 片段对比

| 场/角色 | 自动 P5 | 人工 V1 | 差异 |
|---------|---------|---------|------|
| B 铺垫 | 3121–3143 | 3122–3144 | 基本一致；已 live_verified |
| B 扳平 | 5619–5641 | 5646–5668 | 自动偏早 ~25s，缺角球后破门 |
| B 反超 | 6788–6810 | 6780–6802 | 自动偏晚，庆祝偏多 |
| A 开场 | 1303–1325 | 1325–1347 | 自动偏早，过程未证 |
| A 扳平 | 6461–6483 | 6438–6460 | 自动偏晚，庆祝为主 |
| A 反超 | 6766–6788 | 6831–6853 | **自动错事件**；纠正后 ≈ 人工 |

---

## 6. 无法确认 / 待人工复核

1. B 扳平净过程精确 PTS（角球后到板面 2-2）  
2. B 反超射门瞬间精确 PTS（6778–6790 内）  
3. A 开场 0-1 首次 LIVE 精确窗（1325–1410）  
4. A 扳平射门瞬间（6440–6470；庆祝已确认）  
5. 零付费未做逐帧语义模型；上述标 `live_status_unknown`，**不**冒充已验证，**未**发起付费 API

---

## 复现

导出逻辑：`algo/story_video_agent_v3/p6_video_alignment.py`  
验收：`_story_va_outputs/v3/plan2/p6_video_alignment/visual_audit.json`
