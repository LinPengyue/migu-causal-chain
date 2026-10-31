# 咪咕足球故事链 V2 — R2.9 限定核验报告

> 仅执行 `STORY_VA_V2_R2_8_INDEPENDENT_REVIEW_R2_9_TASK.md` 限定任务。  
> **`render_ready=false`** · **`visual_qc_pass=false`** · **`blocked_source_corruption=true`**（3:1 不变）。  
> API/token：**0**。分支：`story-va-video-driven`。

## 1. PTS 精确映射（相对 R2.8 `final_edl.json`）

| 成片时间 (R2.8) | EDL 段 | story offset | **源 PTS** |
|---|---|---|---|
| **51.00s** | `edl_g11` (30.35→57.35 / 3055→3082) | 20.65s | **3075.65s** |
| **60.50s** | `edl_g21` (57.35→73.35 / 3517→3533) | 3.15s | **3520.15s** |
| 60.48–60.70 | 同上 | 3.13–3.35 | 3520.13–3520.35 |

## 2. 追因结论（有证据，非猜测）

### A. ~51.00s（1:1 后观众庆祝）

| 介质 | 观察 |
|---|---|
| 原始 MP4 @3075.65 | **干净**（`green_bad_blocks=0`） |
| R2.8 work clip `clean_004_edl_g11` @20.65 | **干净** |
| R2.8 final @51.00 | **绿色宏块/破碎**（`green_bad_blocks≥2`，bad8x8>0） |

**判定：`decode_or_render_error`**（成片侧；源片同 PTS 未损坏）。  
R2.8 全片 QC 在 50.5–51.5：**0 anomalies / 0 soft candidates** → **阈值漏检**（旧霓虹阈值抓不住短促绿块沙拉）。

**最小修复：** `edl_g11.media_out` **3082→3074.5**（切除进球后非必需的观众特写尾段；**shot 3064.5 / net 3069.3 保留**，仍有 ~5.2s 庆祝）。未用回放/AI/邻帧伪造。

### B. ~60.50s（2:1 进攻铺垫）

| 介质 | 观察 |
|---|---|
| 原始 MP4 @3520.15 | **局部灰白宏块/人物破碎** |
| work `clean_005_edl_g21` @3.15 | **同损** |
| R2.8 final @60.50 | **同损** |

**判定：`source_corruption`**。  
R2.8 QC 在 60.0–61.0 同样 **0 hits** → 漏检。

**最小修复：** `edl_g21.media_in` **3517→3521.0**（跳过 ~3520.15–3520.4；**同一首次直播连续进攻**；**shot 3524 / net 3527.7 / 庆祝→3533 保留**）。未跳中间单帧造成位置突变。

### C. 3:1

仍为源 `~6315–6316` 损坏。**未做转码去花屏。** 继续 `BLOCKED_SOURCE_CORRUPTION`。

## 3. 检测器回归

- 增补 `green_bad_blocks` / `gray_bad_blocks` / `soft_green_mask` 与短促突发规则（写入 `v2_strip_guided_r2_8_visual_qc.py`）。
- 单元测试：`test_v2_strip_guided_r2_9.py`（含 R2.8 保存负例帧，若磁盘存在）。
- R2.9 成片定点：原 51/60.5 对应新区 **48–53s anomalies=0**；g31 损坏仍被检出。

## 4. 产物

根目录：`/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_9_targeted_qc/`

| 路径 | 内容 |
|---|---|
| `story_clean_live_only.mp4` | 新长版 ~130.05s |
| `final_edl.json` | R2.9 EDL |
| `full_video_visual_qc.json` | 全片 QC（208 samples；灰 0；异常主在 g31） |
| `reports/defect_diagnosis.json` | 两处追因 + 3:1 阻塞 |
| `reports/pts_mapping_51_60.json` | PTS 映射 |
| `frames_src/` `frames_r28/` `frames_work/` `frames_r29/` | 同 PTS 对照 |
| `clips/` | 源/成片/work 短片 |
| `goal_source_to_render_mapping.json` | 五球映射 |

## 5. 门禁

```text
render_ready = false
visual_qc_pass = false
blocked_source_corruption = true   # 3:1
candidate_ready_for_human_review = true
```

用户选择未变：提供干净同次首次直播 3:1 源，或书面接受已知源花屏例外。
