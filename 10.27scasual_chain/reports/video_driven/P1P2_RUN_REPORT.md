# Video-Driven P1/P2 — 本轮运行报告

**分支：** `story-va-video-driven`  
**基线：** `462ea11`（三输入路径未改）  
**日期：** 2026-10-28  

## 交付物

| 文件 | 作用 |
|------|------|
| `algo/story_video_agent/global_video_index.py` | P1：ffprobe + 稀疏抽帧 + tesseract OCR → timeline |
| `algo/story_video_agent/story_discovery_video.py` | P2：timeline → T01 discovery + evidence_tasks |
| `algo/story_video_agent/video_only_p1p2.py` | CLI 入口 |
| `algo/story_video_agent/video_only_pipeline.py` | P4 stub（VideoStoryBundle / adapt） |
| `algo/story_video_agent/test_video_driven_p1p2.py` | 合成观测单测 |
| `reports/video_driven/P1P2_AUDIT_AND_DESIGN.md` | 复用清单 + P3/P4 接口 |
| `reports/video_driven/synth_pil2_p1p2/` | 合成视频真 OCR 跑通产物 |
| `reports/video_driven/croatia_sparse_probe/` | 真实比赛稀疏探测（诚实失败/降级） |

## 运行命令

```bash
cd 10.27scasual_chain/algo
PYTHONPATH=. python -m unittest story_video_agent.test_video_driven_p1p2 -v

# 合成比分视频（需自备 MP4；本轮用 PIL 记分牌 + CRF14）
PYTHONPATH=. python -m story_video_agent.video_only_p1p2 \
  --video /path/to/synth.mp4 --out-dir ../reports/video_driven/out \
  --coarse-step 5 --max-coarse-frames 12 --confirm-hits 2

# 仅观测 JSON（无视频）
PYTHONPATH=. python -m story_video_agent.video_only_p1p2 \
  --synthetic-obs obs.json --out-dir ../reports/video_driven/out
```

## 测试结果

### A. 单元测试（合成观测，无 events JSON）

8/8 OK。覆盖：plus-one 去抖、OCR 噪声拒绝、单帧未确认、翻盘发现、非翻盘、CLI。

### B. 合成视频真 OCR（video-only）

输入：`synth_pil2.mp4`（0-0 → 0-1 → 1-1 → 2-1，无任何 events/causal）。

| 指标 | 结果 |
|------|------|
| 耗时 | ~9.2s（12 抽帧级） |
| score nodes | `0:0 → 0:1 → 1:1 → 2:1` |
| discovery_grade | **story**（protagonist=left） |
| evidence_tasks | 5（opening / equalizer / go_ahead / buildup / ending） |
| semantic_verified | false |
| render_ready | false |

验收：**不提供 events/causal，仅从 MP4 得到有证据的比分轨迹与 T01 候选（score-level）。**

### C. 真实比赛稀疏探测（克罗地亚，开发数据）

`--coarse-step 900 --max-coarse-frames 8`，约 24s。

| 指标 | 结果 |
|------|------|
| usable OCR | 1/8 |
| 错误读数 | t=0 误读 `4:2`（片头非 0:0） |
| 有效 plus-one 轨迹 | 无 |
| discovery | **none** |
| 结论 | **不宣称真实转播端到端跑通**；本地 tesseract 对真实记分牌尚不足 |

后续需：更密采样、记分牌检测/模板、或本地轻量检测模型；仍禁止读交付 JSON 伪装成功。

### D. 故意失败场景（单测）

- OCR 闪现 5:5 → `not_plus_one` 拒绝  
- 单次命中 1:0 → 不提交  
- 非翻盘领先路径 → grade=none  
- 跳跃 0:0→3:1 → 不提交  

## 资源

- 依赖：ffmpeg/ffprobe、tesseract（eng）、OpenCV、NumPy；**无付费 API**  
- 合成成功路径：CPU-only，~9s / ~12 帧  
- 未启动大规模 GPU 实验  

## 下一步（待确认后再做）

1. 提升真实记分牌 OCR（检测框 + 多帧投票 + 开场 0:0 锚定）  
2. P3：按 `story_evidence_tasks` 接 coarse/inspect/refine（小规模原型）  
3. P4：`adapt_to_composer_input` 接 narrative_composer（仍 gate `render_ready`）  
4. 另选**未参与开发**新比赛作保留测试（法国不再当未见）  
