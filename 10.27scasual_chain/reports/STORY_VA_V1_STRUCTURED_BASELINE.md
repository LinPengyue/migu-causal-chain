# Story Video Agent V1 — Structured Input Baseline

| 项 | 值 |
|----|-----|
| **版本名** | Story Video Agent V1 — Structured Input Baseline |
| **Git Tag** | `story-va-v1.0-structured-baseline` |
| **Commit SHA** | `462ea11b8af55429def3c4dd3739e7fa9d6c9153` |
| **源分支** | `story-va-phase2c`（封版时 tip = 上述 SHA） |
| **仓库** | `LinPengyue/migu-causal-chain` |
| **封版性质** | 三输入结构化基线；**不**含 Video-Driven / V2 代码 |

> 本文档位于 Tag **之后** 的说明提交（分支 `story-va-v1-baseline`），**不改变** Tag 所钉住的算法源码。运行 V1 算法时请使用 Tag / SHA `462ea11` 对应树。

---

## 1. 输入 / 输出

**输入（固定）：**

```text
video.mp4 + events.json + causal.json
```

**输出（固定）：**

```text
Story Plan + Story Graph + Story Scope + EDL + Summary + clean/QC MP4
```

另含：`phase5_manifest.json`、`qc_pack/`、`candidate_edl.json` 等。

**策略：** `render_ready=false`（候选交付；不得因 JSON 字段自称授权成片）。无付费 API / VLM 默认路径。

---

## 2. 独立运行入口

工作目录建议：`/data2/lpy1/worktrees/migu-story-va-v1`（见隔离说明）。

```bash
cd /data2/lpy1/worktrees/migu-story-va-v1/10.27scasual_chain/algo
git describe --exact-match --tags HEAD   # 期望: story-va-v1.0-structured-baseline（或祖先为该 Tag）

PYTHONPATH=. python -m story_video_agent.phase5_pipeline \
  --video /mnt/data4/migu/<match>.mp4 \
  --events /path/to/events.json \
  --causal /path/to/causal.json \
  --out-dir /data2/lpy1/_story_va_outputs/v1/<run_id>

# 可选：仅当显式传入时使用 glitch profile（禁止自动绑定某场）
#   --glitch-profile ../reports/phase5/match_profiles/croatia_glitch.json

# 跳过渲染（只出 JSON/MD）
#   --skip-render
```

兼容旧入口（Composer / dry-run）：

```bash
PYTHONPATH=. python -m story_video_agent --story-json ... --dry-run
PYTHONPATH=. python -m story_video_agent --story-json ... --compose --causal-json ...
```

**依赖（摘要）：** Python 3.9+、ffmpeg/ffprobe、OpenCV/NumPy；本地规则链路。不提交 API Key。

---

## 3. Tag 内容核对（462ea11）

已确认 Tag 树内包含：

| 类别 | 路径 / 说明 |
|------|-------------|
| Phase5 管线 | `algo/story_video_agent/phase5_pipeline.py`、`phase5_delivery.py`、`narrative_composer.py`、`video_renderer.py` … |
| 门禁 | `internal_verification.py`、`test_verification_gates.py` |
| 四场报告 | `reports/phase5/{croatia,uae_oman,osasuna_celta,france_australia_first_run}/` |
| 法国首次冻结记录 | `france_australia_first_run/{FIRST_RUN_NOTES.md,ALGORITHM_FREEZE_SHA.txt,…}` |
| Phase 5.1 说明 | `reports/phase5_1_fix.md`、`phase5_generalization_evaluation.md` |

**说明：** 法国首次零修改运行笔记中的算法点为 `13cd05b`（当时冻结）；产物目录原样保留在 `462ea11` 树内。正式 **V1 Tag** 钉在后续合入结尾去重 / story-scope 背景规划后的 `462ea11`。

**不含：** `global_video_index.py` / `video_only_*`（V2 video-driven）。

---

## 4. 封版日测试结果（2026-10-28，于 V1 worktree）

在 `462ea11` / Tag 对应树上执行（**未改算法**）：

| 套件 | 结果 |
|------|------|
| `pytest story_video_agent/test_phase5_delivery.py` | **9 passed** |
| `unittest … test_verification_gates` | **10 passed** |
| `unittest … test_phase2c` + `test_phase2c1` | **通过**（日志见 outputs） |
| `unittest … test_media` + `test_dry_run`（子集） | **1 FAIL + 1 ERROR**（见已知缺陷；与 Croatia fixture/`is_candidate` 预期漂移相关，**未为封版改码**） |

日志：`/data2/lpy1/_story_va_outputs/v1/`

**禁止**将 V2（`story-va-video-driven`）合成 OCR / 全场 video-only 结果记入 V1 验收。

---

## 5. 四场视频与产物路径

### 原始比赛 MP4（只读共享，勿复制进 Git）

| 场次 | 路径 |
|------|------|
| 克罗地亚 vs 加拿大 | `/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4` |
| 阿联酋 vs 阿曼 | `/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4` |
| 奥萨苏纳 vs 塞尔塔 | `/mnt/data4/migu/10月27日 25-26赛季西甲第10轮 奥萨苏纳VS塞尔塔 国语.mp4` |
| 法国 vs 澳大利亚 | `/mnt/data4/migu/2022年11月23日 法国vs澳大利亚.mp4` |

### 结构化报告（Git，Tag `462ea11`）

```text
10.27scasual_chain/reports/phase5/croatia/
10.27scasual_chain/reports/phase5/uae_oman/
10.27scasual_chain/reports/phase5/osasuna_celta/
10.27scasual_chain/reports/phase5/france_australia_first_run/   # 首次冻结，勿覆盖
```

### 预览成片（工作区，非 Git 大文件）

```text
/data2/lpy1/_story_va_previews/phase5/
  croatia_story_{clean,qc}.mp4
  uae_oman_story_{clean,qc}.mp4
  osasuna_celta_story_{clean,qc}.mp4
  france_australia_story_{clean,qc}.mp4
```

新 V1 运行请写到：`/data2/lpy1/_story_va_outputs/v1/`（勿写入 V2 目录）。

---

## 6. 已知缺陷清单（封版时冻结认知）

1. **`render_ready` 恒为策略级 false**：候选 clean/QC 可出片，不等于语义授权。
2. **开场失球 live 常缺失**：记分牌可见但动作镜头未定位（法国 first-run 已记录）。
3. **`match_end` 过远拒绝**：终场与最后比分间隔过大时不做结尾实拍。
4. **dry-run fixture 漂移**：`test_dry_run` 对 Croatia `is_candidate` 断言失败；`test_media` Croatia media-only 缺 `missing_setup_visual`（封版日复现；不改 V1 源码）。
5. **Glitch / 进球过程完整性**：依赖显式 profile 与 facet 规则；非全自动视觉语义核验。
6. **法国 first-run SHA 笔记 ≠ V1 Tag**：笔记记 `13cd05b`；V1 正式钉 `462ea11`（含后续 scope/结尾修复，且保留 first-run 目录）。

---

## 7. 与 V2 的关系

| | V1 | V2 |
|--|----|----|
| Tag / 分支 | `story-va-v1.0-structured-baseline` @ `462ea11` | `story-va-video-driven` |
| 输入 | video + events + causal | video-only（规划中） |
| 工作树 | `/data2/lpy1/worktrees/migu-story-va-v1` | `/data2/lpy1/worktrees/migu-story-va-v2` → `/tmp/migu-va2c` |
| 产物根 | `_story_va_outputs/v1`、`_story_va_previews/phase5` | `_story_va_outputs/v2`、`_story_va_previews/video_driven` |

详见同目录 `V1_V2_WORKTREE_ISOLATION.md`。

**承诺：** V2 迭代不得修改本 Tag 指向的提交内容；对 Composer/Renderer 的适配仅在 V2 分支进行。
