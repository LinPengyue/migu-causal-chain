# Video-Driven Story Agent — 审计与 P1–P4 设计（P1/P2 本轮落地）

**分支：** `story-va-video-driven`  
**冻结基线：** `story-va-phase2c@462ea11`（三输入路径保留，不改既有产物）  
**本轮范围：** P1 + P2 最小可运行 + P3/P4 接口设计（不做全场高成本搜索/批量成片）

---

## 1. 复用 / 改造清单

| 模块 | 判定 | 说明 |
|------|------|------|
| `media.probe_video` | **直接复用** | MP4 元数据 |
| `frames.py` 抽帧/预算 | **复用思路** | P1 自管稀疏抽帧；P3 再接 FrameBudget |
| `score_path.parse_score` / `ScoreNode` / `find_comeback_arc` | **直接复用** | 比分解析与翻盘弧；新增观测→ScoreNode 适配 |
| `score_path.build_score_path` | **不直用** | 依赖交付 events；改用 OCR 观测构建 |
| `recognize.py` / `comeback.build_match_story` | **部分改造** | 逻辑依赖 events/causal；P2 只复用弧发现，不跑全量故事打包 |
| `narrative_composer` / `phase5_delivery` | **P4 复用** | 本轮不接成片；需适配层，禁止伪造全量 events/causal |
| `phase5_pipeline` 三输入入口 | **保留对照** | A 路径基线；B 路径独立 CLI |
| `tools` / `agent` / `phase4a_optimize` 搜索工具 | **P3 复用** | 围绕 evidence_tasks 按需调用 |
| `vision_provider` / 付费 API | **本轮禁用** | 本地 tesseract CLI；无付费 VLM |
| `phase4e1_build` 硬编码 | **不用** | 历史场次专用 |

**禁止：** video-only 路径隐式读取 `交付_out` / `story_t01` / causal JSON。

---

## 2. P1：全局轻量感知（已实现）

`story_video_agent/global_video_index.py`

- 输入：仅 MP4  
- 输出：`global_video_index.json`、`score_timeline.json`  
- 手段：ffprobe + 稀疏抽帧 + 记分牌 ROI + **本地 tesseract**（无 pytesseract 包则直接调 CLI）  
- 比分时序去抖：连续命中 / plus-one 约束（复用 `ScoreNode` 语义）  
- 不确定 → `unknown` / `conflict`，不臆造比分  
- 降级：OCR 全失败时仍输出空 timeline + 明确 `degraded` 状态  

---

## 3. P2：比分轨迹 → T01 Discovery（已实现）

`story_video_agent/story_discovery_video.py`

- 消费 P1 `score_timeline` → `find_comeback_arc`  
- 输出：`story_discovery.json`、`story_evidence_tasks.json`  
- `story` / `candidate` / `none`；比分级发现 ≠ 语义已验证  
- 任务含搜索窗、必做标记、终止条件；**不从旧 JSON 抄答案**  

---

## 4. P3/P4 接口设计（本轮不实现全量）

### P3 局部证据（设计）

```
EvidenceTask → coarse_search_interval → inspect_story_window
  → read_scoreboard_window / scan_reaction_window → refine_search_window
  → StoryEvidenceItem { media_in/out, frame_ids, labels, confidence,
                        relation_candidates[temporal|narrative|causal],
                        semantic_verified=false }
```

写入 `story_evidence.json`；`causal` 边仅在局部规则+视觉一致时标记 `hypothesized`，默认不 `proven`。

### P4 编排接入（设计）

```
VideoStoryBundle {
  score_timeline, discovery, evidence_tasks, evidence_items?,
  teams_hypothesis?, ending_status
}
  → adapt_to_composer_input()  # 内部 IR，非伪造交付 events
  → narrative_composer / phase5_delivery（候选成片）
```

CLI 预留：`python -m story_video_agent.video_only_pipeline --video …`（P4 落地）。  
本轮入口：`python -m story_video_agent.video_only_p1p2 --video … --out-dir …`

---

## 5. 数据隔离

| 用途 | 比赛 |
|------|------|
| 冻结三输入基线 | `462ea11` 四场产物，只读 |
| P1/P2 研发/冒烟 | 合成比分 + 短合成帧；可选极稀疏真实抽帧（开发用，不作未见测试） |
| 真正保留测试 | **另选未参与开发的新比赛**（法国已用过，不再当未见） |

---

## 6. P3 接口（设计，本轮未实现全量搜索）

**输入：** `story_evidence_tasks.json` + MP4 +（可选）`global_video_index.json`  
**输出：** `story_evidence.json`

```text
StoryEvidenceItem {
  task_id, media_start_sec, media_end_sec,
  frame_ids[], labels[],  # live_goal | shot | celebration | replay | unresolved
  relation_candidates: [{kind: temporal|narrative|causal, status: hypothesized|unresolved}],
  confidence, semantic_verified: false,
  retrieval: {tool_trace[], budget_used, stopped_reason}
}
```

工具绑定（复用现有 agent tools，按 task 调度，不全场跑）：

| task 前缀 | 工具序列 |
|-----------|----------|
| `locate_*_goal` | coarse_search_interval → inspect_story_window → read_scoreboard_window → refine |
| `find_relevant_buildup` | coarse → scan_reaction_window（可早停） |
| `verify_story_ending` | read_scoreboard_window 稀疏 |

规则：缺必要证据 → `unresolved`；禁止把先后序直接标 `causal.proven`。

---

## 7. P4 接口（设计 stub 已落）

`video_only_pipeline.VideoStoryBundle` → `adapt_to_composer_input()`  
- 不伪造全量 events/causal  
- `semantic_verified=false` 时拒绝 `render_ready`  
- 成片仍走 `narrative_composer` / `phase5_delivery`（候选或仅报告）  
- 三输入 `phase5_pipeline` 保留作 A 路径对照  

CLI：`python -m story_video_agent.video_only_pipeline --video … --stage p1p2`
