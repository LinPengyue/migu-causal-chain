# 咪咕足球故事链 V2 — R2.8 报告

> `render_ready=false`。`visual_qc_pass=false`。`blocked_source_corruption=true`（3:1 原片不可恢复色带）。  
> 分支：`story-va-video-driven`。API/token：**0**。

## 1. 对用户复核项的结论

| 项 | 结论 |
|---|---|
| **58.2–59.0s（R2.7）** | **源片损坏**（非 concat）：源 `3515.85–3516.65` 与 R2.7 同 PTS 一致出现横向色带/人物破碎。R2.8 将 `edl_g21` 起点从 `3515` 提到 **`3517.0`**（干净广角直播），止于 `3533`；**2:1 射门 3524 / 入网 3527.7 保留**。新成片 g21 开段无再命中该 P0。 |
| **3:1 ~85.7–87s（R2.7）→ R2.8 ~84–85s** | **仍为原片 `source_band_glitch_during_live_shot`（~6315–6316）**。无更干净同源首次直播拷贝；禁止回放/邻帧/AI 补帧冒充修复。门禁：**`BLOCKED_SOURCE_CORRUPTION`**。 |
| **102.75–103.25s（R2.7）** | 对应 `edl_score_3_1` 源 ~6408.1–6408.6：**右下角轻度碎片，属源片 P1**，未升级为独立 P0。 |
| **4:1 收尾** | 增加真实 LIVE `edl_final_live_reaction`：`7908–7922`（伤停补时末段→板凳/赛后反应，直播角标在）。**未**使用 7950+ 他场/演播室；**未**声称精确终场哨 PTS（无单独音频哨声核验）。 |
| **条带漏检** | 新检测器在 R2.7 负例上：**灰屏=0 仍检出 58s/86s 色带宏块**，回归通过。 |

## 2. 工程改动

- `algo/story_video_agent/v2_strip_guided_r2_8_visual_qc.py` — 灰屏 + 霓虹色带/宏块/局部色破 + 时序候选；保留 evidence；永不 `render_ready=true`。
- `algo/story_video_agent/v2_strip_guided_r2_8_build_edl.py` — g21 修剪、g31 BLOCK 标注、自然收尾段。
- `algo/story_video_agent/test_v2_strip_guided_r2_8.py` — 单元 + 负例辅助。
- 渲染复用 R2.7 `filter_complex` 重编码路径。

## 3. 产物路径（独立目录，未覆盖 R2.7）

根目录：`/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_8_visual_gate/`

| 文件 | 说明 |
|---|---|
| `story_clean_live_only.mp4` | 新长版 ~141.55s |
| `story_qc_overlay.mp4` | QC 叠字版 |
| `final_edl.json` | R2.8 EDL |
| `full_video_visual_qc.json` | 全片扫描（309 samples；灰 0；色带/宏块异常 24，主集群在 g31） |
| `negatives/r27_negative_scan.json` | R2.7 58s/86s 负例回归 |
| `goal_source_to_render_mapping.json` | 五球映射 |
| `qc_anomaly_clips/` | 可播放对照短片（R2.7 破损、源片、R2.8 g21 开段、g31、收尾） |
| `frames_r27/` `frames_src/` `frames_r28/` | 同 PTS 对照帧 |

## 4. 五球 Live-Only（摘要）

| 比分 | 源窗口 | 射门/入网 | 备注 |
|---|---|---|---|
| 0:1 | 975.8–988 | 982.06 | 首次直播 |
| 1:1 | 3055–3082 | 3064.5 / 3069.3 | + 角球铺垫 3042.85–3055 |
| 2:1 | **3517–3533** | 3524 / 3527.7 | R2.8 修剪源色带；灰屏 3535 仍排除 |
| 3:1 | 6305–6332 | ~6314 / ~6320 | **源损坏保留 + BLOCK** |
| 4:1 | 7740–7760 | 7746.78 / 7748.1 | + 记分牌 7857.37–7860.87 + 自然收尾 7908–7922 |

## 5. 门禁与用户选择

```text
render_ready = false
visual_qc_pass = false
blocked_source_corruption = true
candidate_ready_for_human_review = true
```

在 **取得同次首次直播的干净 3:1 源拷贝**，或 **用户书面批准带已知源花屏交付例外** 之前，不得升级交付。

## 6. 测试 / API

- `PYTHONPATH=algo python3 -m unittest story_video_agent.test_v2_strip_guided_r2_8 -v` → OK  
- R2.7 负例：`all_negatives_detected=true`，且 `n_gray=0` 同时 `n_band>0`  
- DeepSeek/Qwen/Story Planner：**未调用**（API=0，token=0）

## 交付 commit

`f296891` (`f29689175fca6c8d40f01e1df6d93eb1cb82282d`)
