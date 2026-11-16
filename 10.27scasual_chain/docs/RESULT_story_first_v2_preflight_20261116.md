# Story-First v2 实片离线预检（2026-11-16）

HEAD: `5aef37cfa96e7ad2d9581b0df642f4cf20f308ff`  
Server out: `/tmp/lpy1_story_first_v2_preflight_20261116/`  
Artifacts: `docs/artifacts_story_first_v2_preflight_20261116/`  
**HTTP / 模型 API：0**（`--enable-story-first --offline`，复用 Causal-4 历史产物）

## 1. 回归（Cursor 验收步骤 1）

```text
tests/test_v3a_story_first_closed_loop.py
tests/test_v3a_story_first_scheme_a.py
tests/test_v3a_v2_story_first_evidence_adapter.py
tests/test_v3a_story_first_poc.py
tests/test_v3a_story_first_local_patterns.py
tests/test_v3a_continuous_broadcast_phase.py
```

结果：**74 passed**

## 2. 同场次离线预检（步骤 2）

输入（与 P14 / Causal-4 同 SHA）：

| 资产 | 路径 | SHA 前缀 |
|------|------|----------|
| source mp4 | `/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4` | `a66147f7…` |
| Phase5 EDL/plan | `…/04_phase5/` | EDL `b38434b9…` plan `ba64c215…` |
| events | `…/01_enrich/events_enriched.json` | `33958b10…` |
| 复用产物 | `/tmp/lpy1_scheme_a_causal4_run_20261116` | gen+score |

命令要点：`--enable-story-first --story-first-artifacts-dir <causal4> --build-local-first-live-evidence --offline --max-rounds 1 --no-smoke-render`

### `story_first/story_first_pool.json`

| 区间 | 锚点 | 状态 | 事件量 | 候选 |
|------|------|------|--------|------|
| **interval_01** | opening→equalizer `[1347.123, 6436.924]` | **REUSED**（历史 Causal-4） | （历史 240 rich / 530 inventory） | **5**（`interval_01:H1…H5`） |
| **interval_02** | equalizer→go_ahead `[6458.924, 6829.456]` | **PREPARED_ONLY** | inventory **58** / rich **58** | 0（待付费生成） |

复用核对：`artifact_status=OBSERVATION_QUEUE_ONLY`，评分状态 `REAL_MODEL_PRIOR_NOT_VIDEO_VERIFIED`，已记录 `prepared` / `hypotheses` / `ranking` SHA。

### Planner 可见提案

- 池内 **5** 条，全部来自 interval_01。
- 字段含 `scope` / `events` / `relations` / `causal_mechanism` / `major_uncertainty`。
- **不含**四维数值分或 `model_priority`（分数只在区间 ranking 产物）。

### interval_02 付费就绪（未调用）

- 已写出 `generator_request.json`
- 官方 tokenizer 测量：**12757** input tokens；`max_out=4500` 时 worst-case 项目估价约 **$0.0046**（远低于 $0.10）
- 状态停在 `PREPARED_ONLY`（offline / 无 API）

## 3. 尚未完成（步骤 3–4，需预算授权）

离线轮次 **未产生** `story_first_trial.json` / `story_first_feedback.json`；`first_live_window_ledger.windows=[]`（无试剪插入窗口）。

待授权后验证：

1. interval_02 真实 Generator（+ Scorer）
2. 开/关 `--enable-story-first` 对照
3. 候选窗口独立 FIRST_LIVE（含 `STORY_ACTION`）
4. 试剪 → Renderer → 双视频 Verifier → 人工审片

正式交付仍走现有 Phase 8 最佳版本规则；当前双视频抽帧只支持修订/人工，不作质量宣称。

CLI：`delivery_label=BLOCKED`（预期，offline 未修订成片），`http_calls=0`。
