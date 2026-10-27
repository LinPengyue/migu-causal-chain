# Phase 4A — 真实多模态 API 视频理解与故事镜头优化

**分支**: `story-va-phase2c`  
**前置同步**: Phase 3B commits `63e7d0d`、`7277fd2` 已 **普通 push** 至 `origin/story-va-phase2c`（未 force-push）。

## 计费门控（本次未发起真实请求）

本机未配置 `STORY_LLM_API_KEY` / `OPENAI_API_KEY`，且未设置 `STORY_PHASE4A_REAL=1`。

| 开关 | 作用 |
|------|------|
| `STORY_API_ENABLE=1` | 允许真实 HTTP |
| `STORY_PHASE4A_REAL=1` | Phase 4A 显式授权（独立开关） |
| `STORY_API_SMOKE=1` | 联调显式开启 |
| `STORY_API_MAX_CALLS` / `STORY_API_MAX_COST_USD` | 硬性预算 |

默认路径：`force_mock=True` — **对真实克罗地亚视频抽帧**，VLM/Planner 走 Mock，HTTP=0，费用=0。

真实实验示例：

```bash
STORY_API_ENABLE=1 STORY_PHASE4A_REAL=1 STORY_API_SMOKE=1 \
STORY_LLM_BASE_URL=... STORY_LLM_API_KEY=... STORY_VLM_MODEL=... \
STORY_API_MAX_CALLS=12 STORY_API_MAX_COST_USD=0.50 \
PYTHONPATH=algo python -m story_video_agent.phase4a_optimize \
  --story-json reports/story_t01/2022-11-28\ 克罗地亚vs加拿大.json \
  --video-path "/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4" \
  --plan-json reports/story_compose_phase3a1_croatia.json \
  --out-dir _local_render/phase4a_real \
  --mode vlm-only \          # 或 planner-vlm-loop
  --real \
  --v1-summary _local_render/phase3b/croatia_preview_summary.json
```

## 本次 Mock+真视频联调结果

产物目录：`/tmp/migu-va2c/10.27scasual_chain/_local_render/phase4a/`

| 产物 | 路径 |
|------|------|
| Preview v2 MP4 | `_local_render/phase4a/croatia_preview_v2.mp4` |
| Plan / EDL v2 | `croatia_plan_phase4a.json` / `croatia_candidate_edl_phase4a.json` |
| Contact sheet | `review_v2/contact_sheet.jpg` |
| Review manifest | `review_v2/review_manifest.json` |
| 实验 JSON | `phase4a_experiment_report.json` |

### API / 预算

- `real_api_executed`: **false**（mock）
- HTTP attempts: **0** · est cost: **$0**
- 抽帧: used **6** / budget **12**（equalizer 4 + go_ahead locate 2）
- 耗时: **~31 s**

### 搜索起点（仅 seed，不预设正确）

| 目标 | Seed | 说明 |
|------|------|------|
| 扳平进球 | ~3065.903s | Phase 3A.1 live 候选 |
| 扳平记分牌 | ~3145.98s | 比分确认锚点 |
| 反超记分牌 | ~3697.35s | 搜索反超进球的上界参考 |

### v1 → v2 对比

| 项 | v1 (3B) | v2 (4A mock) |
|----|---------|--------------|
| Preview 时长 | 17.16 s | **17.68 s** |
| 分辨率 | 1280×720 | 1280×720 |
| 裁切 / 占位 | 5 / 1 | 5 / 1 |
| 缺失/blocked 段 | 1 | 1（go_ahead 仍未可信定位） |
| 扳平窗 | 3061.9–3073.9 | **3059.9–3071.9**（观察后微调） |
| render_ready | false | **false**（禁止模型 verified 提权） |

go_ahead：Mock 观察为 `shot`+`uncertain`（conf=0.28），未达调整阈值；仍 blocked/占位「镜头待定位」。Mock 观察不得写成已核实进球。

## 实现要点

1. `phase4a_config.py` / `phase4a_optimize.py`：多轮抽帧 → VLM 标签（shot/goal/…）→ 规则（+可选 LLM）改窗 → 回填 plan  
2. `strip_external_trust_flags` + `internal_verification`：模型 `pipeline_verified` 无效  
3. Phase 3B renderer 输出 preview v2 + review 辅助  
4. 模式区分：`vlm-only` vs `planner-vlm-loop`  
5. 测试：`test_phase4a.py`（门控、伪造剥离、合成闭环、克罗地亚 mock）

## 诚实边界

本次**没有**计费多模态 API 调用，因此尚不能声称「模型实际看懂进球」。已具备：真视频抽帧、观察→改窗→预览闭环、以及一键真实实验入口。配置 Key 并设置 `STORY_PHASE4A_REAL=1` 后即可产出真实 VLM 证据。
