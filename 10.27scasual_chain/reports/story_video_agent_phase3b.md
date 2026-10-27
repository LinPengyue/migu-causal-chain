# Phase 3B — 真实比赛视频剪辑与审核样片

**分支**: `story-va-phase2c` · **范围**: `10.27scasual_chain` 仅 Story Video Agent  
**Git commit**: `63e7d0d6277319b7d6a0edafae3f2ae0196ca31f` (`story-va-phase2c`)

## 结论

- 外部 JSON 的 `pipeline_verified` / `time_pipeline_verified` **不能**抬升 `candidate_edl` → `render_ready_edl`。
- 仅 `internal_verification_pipeline`（`algo/story_video_agent/internal_verification.py`）可授予正式成片资格。
- `preview` / `final` FFmpeg 模式严格隔离；`final` 在 `render_ready=false` 时硬失败，不降级。
- 克罗地亚真实比赛已产出可播放短版 **preview MP4**、contact sheet、`review_manifest.json`。

## 服务器产物路径（不入库）

| 产物 | 路径 |
|------|------|
| Preview MP4 | `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase3b/croatia_preview_short.mp4` |
| 渲染摘要 | `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase3b/croatia_preview_summary.json` |
| Contact sheet | `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase3b/croatia_review/contact_sheet.jpg` |
| Review manifest | `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase3b/croatia_review/review_manifest.json` |
| 中间 clips | `/tmp/migu-va2c/10.27scasual_chain/_local_render/phase3b/work_croatia/clips/` |
| 源视频（只读） | `/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4` |
| 输入 Story Plan | `reports/story_compose_phase3a1_croatia.json` |

`_local_render/`、`*.mp4`、截图已加入 `.gitignore`，不提交大文件。

## 克罗地亚 preview 实测

| 项 | 值 |
|----|----|
| 时长 | **17.16 s** |
| 分辨率 | **1280×720** |
| fps | ~24.8 |
| 片段数 | **6**（裁切 5 + 占位 1） |
| FFmpeg | 全部 returncode=0 |

片段原片位置（`max_clip_sec=3`）：

1. `seg_setup_deficit` 铺垫 · cut · 1075.06–1078.06s  
2. `seg_equalizer_goal_action` 转折 · cut · 3061.90–3064.90s  
3. `seg_equalizer_scoreboard` 转折 · cut · 3141.98–3144.98s（比分确认，非进球动作）  
4. `seg_go_ahead_scoreboard` 高潮 · cut · 3693.35–3696.35s（比分确认）  
5. `seg_go_ahead_goal_pending` 高潮 · **placeholder「镜头待定位」**（无可信进球窗，未虚构）  
6. `seg_ending` 收尾 · cut · 7942.16–7945.16s  

`final` 模式对同一 plan：**硬拒绝**（`render_ready=false`）。

## 新增 / 关键模块

- `internal_verification.py` — 剥离外部信任；媒体界内核验；唯一 promote 路径  
- `video_renderer.py` — preview/final；裁切/转码/拼接；占位卡；叠加「内部审核样片 / 镜头未核实」  
- `review_assist.py` — 起/中/终截图、contact sheet、`review_manifest.json`、导入桩（不可提权）  
- `test_phase3b.py` — 合成视频（越界/无音频/重复镜/空 EDL/伪造/final 硬失败）+ 克罗地亚 preview  
- CLI：`--render preview|final --plan-json ... --video-path ... --out ... [--review-dir]`

## 验收测试

```text
PYTHONPATH=algo python -m unittest \
  story_video_agent.test_phase3a1 \
  story_video_agent.test_phase3b -v
# + 既有 phase3a / 2c / 2c1 / media / dry_run 均 OK
```

## 使用示例

```bash
PYTHONPATH=algo python -m story_video_agent \
  --plan-json reports/story_compose_phase3a1_croatia.json \
  --video-path "/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4" \
  --render preview \
  --out _local_render/phase3b/croatia_preview_short.mp4 \
  --work-dir _local_render/phase3b/work_croatia \
  --max-clip-sec 3 \
  --review-dir _local_render/phase3b/croatia_review
```
