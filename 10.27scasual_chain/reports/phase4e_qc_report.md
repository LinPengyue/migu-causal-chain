# Phase 4E — QC 报告（可播放预览 + 接缝/叙事）

基准：`story-va-phase2c@60c313c`（执行时已 ff-only 更新）。**无付费 API** · **`render_ready=false`** · 未改 main。

## 1. Phase4D 基线预览探测

路径：`_local_render/phase4d/croatia_preview_phase4d_full.mp4`

| 项 | 结果 |
|----|------|
| 时长 | **91.668s** |
| 画面 | h264 1280×720 ~25fps |
| 音轨 | **aac 44.1kHz stereo（存在）** |
| 段数 | 7 cut / 0 placeholder |
| 黑帧 `blackdetect d=0.15` | 未检出 |
| 静音 `silencedetect -35dB d=0.5` | 未报告长静音 |
| 响度 | **I ≈ -30.4 LUFS**，LRA 9.3（偏静，未做响度统一） |
| 打开 | `ffplay`/`ffmpeg` 解码 **OK** |

### 7 段预览时间轴 QA

| # | 段 | 预览内时间 | 源窗（实际切入） | 笔记 |
|---|----|------------|------------------|------|
| 1 | 铺垫 | 0–12.0 | 1075–1087 | OK |
| 2 | 蓄力 | 12.0–26.0 | **3038–3052** | `max_clip_sec=14` 截断；原计划到 3064 |
| 3 | 扳平动作 | 26.0–37.6 | 3063.5–3075 | OK |
| 4 | 1:1 牌 | 37.6–49.6 | 3142–3154 | OK |
| 5 | 反超动作 | 49.6–63.6 | 3518–3532 | OK |
| 6 | 2:1 牌 | 63.6–77.6 | 3594–3608 | OK |
| 7 | FULL TIME | 77.6–91.7 | 7928–7942 | 候选收尾 |

## 2. 接缝（P1）

### EDL 计划：0.5s 重叠
- 蓄力 `[3038, 3064]` ∩ 扳平 `[3063.5, 3075]` = **`[3063.5, 3064]`**
- `phase4d_cut_quality_checklist.json` → `ok=false`（属实，不得静默通过）

### Phase4D 成片实际：11.5s 叙事跳切
- 因截断，蓄力实际出点 **3052** → 下一镜 **3063.5**，跳过禁区压迫尾段
- 证据：`_local_render/phase4e/seams/contact_preview_jump_3052_to_3063.jpg` 与 seam 短片

### Phase4E 修复（两版新预览）
- 蓄力改为 **`[3038, 3063.5]`**，扳平 **`[3063.5, 3075]`** → **abut，重叠 0**
- 蓄力保留完整 25.5s（不再 14s 截断）

## 3. 2:1→4:1 叙事（本地搜索，非臆造）

| 进球 | 入网≈ | 动作时牌 | score_path 牌 | 候选窗 |
|------|-------|----------|---------------|--------|
| 3:1 | **6318.5** | 仍 2:1（直播） | 6408.7 | 6312–6328 |
| 4:1 | **7749** | 仍 3:1（直播） | 7858.37 | 7740–7756 |

记分牌时间**未**当作进球动作。delivery `event_000153` Goal@7747.43；causal 3:1 seed@6317.199。

## 4. 两版审核预览（请用户观看）

| 版本 | 路径 | 时长 |
|------|------|------|
| **短版+文字桥** | `_local_render/phase4e/croatia_preview_phase4e_short_bridge.mp4` | ≈108.2s |
| **长版+3:1/4:1 动作** | `_local_render/phase4e/croatia_preview_phase4e_long_with_goals.mp4` | ≈159.3s |

播放：
```bash
ffplay -autoexit '/tmp/migu-va2c/10.27scasual_chain/_local_render/phase4e/croatia_preview_phase4e_short_bridge.mp4'
ffplay -autoexit '/tmp/migu-va2c/10.27scasual_chain/_local_render/phase4e/croatia_preview_phase4e_long_with_goals.mp4'
```

审核包：`_local_render/phase4e/review_bundle/`（含帧证据、接缝 sheet、两版预览）。

## 5. 门禁

- 全部 `candidate_only`；`render_ready=false`；`render_ready_edl=[]`
- 语义：`pending_independent_human_review`（**未**自动签发）
- `review_ready=true` **仅表示材料可审**，≠ production / ≠ render_ready
