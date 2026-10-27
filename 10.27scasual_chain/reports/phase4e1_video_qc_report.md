# Phase 4E.1 Video QC Report — 花屏根因与修复证据

**分支：** `story-va-phase2c`  
**范围：** 克罗地亚 vs 加拿大 T01_comeback 内部审核预览（candidate_only）  
**硬性结论：** 花屏**根因在原片 HEVC 码流**，非 Phase 4E 的 H.264 截取/concat 新引入；4E.1 通过**避开损坏媒体时间窗**修复预览，自动化抽帧扫描未再检出同类失真 → **本阶段视频 QC 通过（preview / review_ready）**。  
**仍保持：** `render_ready=false`，非正式成片授权。

---

## 1. 现象与时间映射

ChatGPT 对 Phase 4E 样片的报告：

| 预览版本 | 预览时间 | 对应片段 | 源媒体时间（约） |
|---------|---------|---------|----------------|
| 短版 / 长版 | ~85s | `seg_go_ahead_scoreboard_closer` | ~3604 |
| 长版 | ~92.5–93.5s | `seg_third_goal_action` | ~6315.5–6316.5 |
| 长版 | ~135–135.5s | `seg_fourth_scoreboard` | ~7856.4 |

工作片段时间轴（Phase 4E，ffprobe）：短版 2:1 牌 = preview [75.12, 89.14]；长版 3:1 = [89.14, 105.17]；4:1 牌 = [133.22, 145.24]。

---

## 2. 分层诊断（必须定位发生层）

### 2.1 最终预览 MP4

路径：`_local_render/phase4e/croatia_preview_phase4e_{short_bridge,long_with_goals}.mp4`  
抽帧：`_local_render/phase4e1/diag/preview/`  
**结果：** 报告时刻均可见绿色马赛克 / 霓虹色水平条带 / 运动拖影。花屏**存在于最终预览**。

### 2.2 独立 work 片段（截取后、concat 前）

同点抽帧：`_local_render/phase4e1/diag/clip/`  
- `short_005` t≈10s（→ media ~3604）  
- `long_006` t≈4s（→ media ~6316）  
- `long_009` t≈2.3s（→ media ~7856.7）  

**结果：** 与最终预览一致失真。花屏**在单段截取后已存在** → 排除「仅 concat/copy 拼接引入」。

### 2.3 原片（HEVC Main 1080p）

源：`/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4`  
codec：`hevc` / `yuv420p` / ~50 fps。GOP 关键帧间隔约 **5s**（例：3594.16, 3599.12, 3604.08…）。

对照实验：

| 方法 | 说明 | 损坏时刻结果 |
|------|------|-------------|
| `-ss` before `-i` 单帧 | 与旧 cut 管线同类 | 花屏 |
| Hybrid（粗 seek + 精 `-ss`）再编码 | 规避单纯 input-seek 歧义 | **仍花屏** |
| 从上一关键帧 `-c copy` 再解码 | 码流级隔离 | **KF 帧干净；同 GOP 内损坏 PTS 仍花屏** |

证据目录：

- `_local_render/phase4e1/diag/source_fast/`
- `_local_render/phase4e1/diag/reencode_test/`
- `_local_render/phase4e1/diag/copy_test/`（`*_copy_t0.jpg` 干净 vs `*_copy_t*.jpg` 花屏）

**结论：** 故障层 = **原片 HEVC 码流在特定 PTS 的 P/B 帧损坏**（解码器从合法 IDR 前进后仍输出马赛克）。  
**不是** Phase 4E 的 libx264 重编码或 concat demuxer 单独制造的问题（它们只是忠实继承了坏源帧）。

已确认的源损坏区间（media 秒）：

| media_in | media_out | 标签 |
|----------|-----------|------|
| 3603.6 | 3604.8 | ga_board_2_1_green_mosaic |
| 6315.8 | 6316.7 | third_goal_approach_neon_band |
| 7855.6 | 7856.5 | fourth_board_green_band |

邻近干净参照：`3599`/`3602`（含 LIVAJA 底部比分条）、`6318.5`（3:1 入网）、`7855`/`7857`（4:1 牌）。

---

## 3. 修复策略（避开坏段，非「盲目重转码即宣称修复」）

| 镜头 | Phase 4E 窗口 | Phase 4E.1 窗口 | 依据 |
|------|---------------|-----------------|------|
| 2:1 比分牌 | 3594–3608 | **3599.5–3603.0** | 避开 ~3604；保留 2:1 + LIVAJA 条 |
| 3:1 进攻 | 6312–6328 | **6317.0–6328.0** | 避开 ~6316；**保留入网≈6318.5** |
| 4:1 比分牌 | 7854.37–7866.37 | **7857.0–7860.5** | 避开 ~7856 |

管线加固（代码）：`video_renderer._cut_segment` 默认 **hybrid accurate seek** + 片头强制关键帧；4E.1 构建脚本**禁用 `max_clip_sec`**，避免再次截断蓄力尾段。

---

## 4. 修复后回归（新预览）

| 产物 | 路径 | 时长 | 响度（loudnorm 测） |
|------|------|------|---------------------|
| **长版主方案** | `_local_render/phase4e1/croatia_preview_phase4e1_long_primary.mp4` | **124.04s** | I≈**-15.78 LUFS**, TP≈**-1.41 dBTP** |
| 短版对照 | `_local_render/phase4e1/croatia_preview_phase4e1_short_bridge.mp4` | 95.97s | I≈**-15.99 LUFS**, TP≈**-1.47 dBTP** |

工作区可读副本：`/data2/lpy1/_story_va_previews/croatia_preview_phase4e1_*.mp4`

### 4.1 原花屏位点（新时间轴）抽帧

| 角色 | 新 preview 区间 | QC 静帧 |
|------|----------------|---------|
| 2:1 牌 | 71.5–75.0 | `qc_stills/long_ga_board_*.jpg` — **干净** |
| 3:1 进攻 / 入网 | 75.0–86.0；入网≈76.5 | `long_third_goal_*.jpg`, `long_third_goal_ball_net_p076.5.jpg` — **干净** |
| 4:1 牌 | 103.5–107.0 | `long_fourth_board_*.jpg` — **干净** |

### 4.2 全片 neon/magenta 扫描

`_local_render/phase4e1/qc_artifact_scan.json`：  
- 长版每 2s 抽帧（0–122s）：**0 BAD**  
- 上述三焦点每 0.5s：**0 BAD**  
- dense max `neon_rows`≈0.008（对照坏帧曾 ≥0.19）

### 4.3 接缝 / 截断回归

- 蓄力 work clip duration = **25.524s**（3038–3063.5）— **未**被 `max_clip_sec` 截断  
- 扳平 abut 3063.5 保留；seam 静帧见 `qc_seams/`  
- blackdetect：未见异常长黑场（标题卡为深色底，属设计）

### 4.4 音频

内部预览目标：`I=-16 LUFS`, `TP=-1.5 dBTP`, `LRA=11`（**非正式咪咕交付规范**）。  
4E 约 −30.6 LUFS → 4E.1 约 −16 LUFS；保留现场起伏（dynaudnorm 轻处理 + 成片 loudnorm）。

---

## 5. 门禁状态

| 项 | 状态 |
|----|------|
| 花屏分层定位完成 | ✅ 原片码流 |
| 新预览关键位点无同类失真 | ✅ |
| `candidate_only` | ✅ |
| `render_ready` | **false**（不变） |
| `review_ready` | **true**（仅内部画面复审；非正式生产授权） |
| 付费 API | 未使用 |
| 合并 main | 未做 |

---

## 6. 审核清单（供 ChatGPT / 人工）

1. 长版 ~73s：2:1 牌是否干净、是否仍能读出比分。  
2. 长版 ~76.5s：3:1 球进网是否完整、有无马赛克。  
3. 长版 ~105s：4:1 牌是否干净。  
4. 蓄力→扳平（preview ~40.5s）是否仍连续（无 11.5s 跳切）。  
5. 音量是否可正常听清欢呼/解说。  
6. 标题卡是否过喧宾夺主。

**播放：**

```bash
ffplay -autoexit '/data2/lpy1/_story_va_previews/croatia_preview_phase4e1_long_primary.mp4'
# 或
ffplay -autoexit '/tmp/migu-va2c/10.27scasual_chain/_local_render/phase4e1/croatia_preview_phase4e1_long_primary.mp4'
```
