# V3 ↔ V1 Input Parity Audit — Can 8.31 Feed Stock V1?

**Branch:** `story-va-v3-plan2`  
**Baseline:** `b356b2d`  
**Paid API:** 0  
**Gold / human `*_causal.json` as runtime input:** **forbidden** (offline compare only)  
**`render_ready`:** **false** (no replay-exclusion QC on auto EDL)

Artifacts:
- B: `/data2/lpy1/_story_va_outputs/v3/plan2/v1_parity_B_osasuna/`
- A: `/data2/lpy1/_story_va_outputs/v3/plan2/v1_parity_A_uae_oman/`
- Adapter: `algo/story_video_agent_v3/v1_causal_adapter.py` + `v1_parity_cli.py`

---

## Priority answer

### **不能。** 冻结 8.31 全场 reinfer **无法**生成「足够完整」的 V1 故事输入。

根因不是 V1 Planner/Composer 坏了，也不是单纯「Schema 字段名没对齐」，而是：

1. **交付 `events.json` 检测流里没有 `Goal` / `进球` 事件类型**（B: 0；A: 0）。  
2. **8.31 production strip 因此产出 `outcome=0`**（B 65 链：special 47 / danger 17 / correction 1；A 79 链：special 43 / danger 34 / correction 2）。  
3. **V1 `story_chain` 选关键进球依赖人工因果链里的中文终端** `进球|乌龙球|头球破门` + `t_ms`，并在记分牌附近窗口匹配。  
4. 人工 `*_causal.json` 里的 `进球` **不是** detector 同名 `event_id` 的语义行（同 ID 在 raw 中多为 Pass，且时间完全不同）——那是**标注层 Goal 动作时间**，不能也不应从 8.31 复述进 V3。

| 能力 | 8.31→V1 自动链 | 人工 V1 链 |
|------|----------------|------------|
| 事件 ID 覆盖率 | B ≈ **99.7%** / A ≈ **99.6%** | N/A（标注链） |
| `结果链` / outcome | **0** | B 18 / A 8 |
| Goal 终端行 | **0** | 多条 `进球` + `t_ms` |
| V1 故事 `has_story` | true（靠比分弧） | true |
| V1 故事内进球事件 | **0** | B 3 / A 3（弧上选用） |
| Compose 进球动作窗 | **全部 missing**（仅有记分牌锚点） | 有 `*_goal_action` media_in/out |
| 可正式 `render_ready` | **否** | 原 V1 另含回放补充段，本阶段亦不视为 V3 成片标准 |

**缺少的关键字段 / 事件 / 关系（按优先级）：**

1. **Goal 动作终端**：`type∈{进球,乌龙球,头球破门}` + 真实首次 LIVE `t_ms`（不可用记分牌确认秒冒充）。  
2. **结果链（outcome）**：以进球（或等价终端）收束的链；当前 strip 只有 special/danger/correction。  
3. **与记分牌单球增量对齐的 live Goal 链**（`is_replay=false`）；人工链大量 `is_replay=true` 进球，V1 会优先 live，但仍依赖标注 Goal。  
4. **显式因果关系边**：V1 实际只用链内 `events[]` 顺序，无独立 edge 字段——**不是**主瓶颈。  
5. **`segment_time_video` 时钟串**：V1 planner **不读**该字段做 PTS——**不是**主瓶颈。  
6. **视频定位 / 回放排除**：本阶段自动输入对齐后，goal_action 仍 unresolved；即使以后补上 Goal `t_ms`，最终 EDL 仍须先做首次 LIVE / 禁回放核验才能 `render_ready`。

---

## 1. V1 原始输入审计

### 读取路径

Stock V1 通过显式路径读取人工交付：

```text
python -m story_chain --events <match>.json --causal <match>_causal.json
python -m story_video_agent --story-json … --compose --causal-json <match>_causal.json
```

本仓库交付文件（对照用）：

- B: `10.27scasual_chain/data/交付_out/10月27日_25-26赛季西甲第10轮_奥萨苏纳VS塞尔塔_国语_causal.json`（33 链）  
- A: `…/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语_causal.json`（25 链）

### Schema（`schema_version: 1.0-min`）

**顶层：** `match_id`, `video_name`, `team_*`, `causal_chains[]`  

**链：** `annotation_id`, `chain_category`∈{结果链,险情链,…}, `causal_chain_subtype`, `is_replay`, `segment_time_*`, `events[]`  

**事件：** `event_id`, `order`, `type`（中文）, `type_en`, `t_ms`, `bz_id`  

**无**独立因果边、无 story_role、无比分、无 media_in/out 文件偏移。

### V1 必需 vs 辅助

| 必需（故事/EDL） | 辅助 / 未用 |
|------------------|------------|
| `causal_chains[].events[]` 含 Goal 类 `type` + `t_ms` | `segment_time_sketch/video`（planner 不解析 PTS） |
| `is_replay`（优先 live） | `bz_id`, colors, `schema_version` |
| `chain_category`（险情/结果） | `causal_chain_other_name` |
| 顶层 `match_id` / 队名 | 显式 relation graph（不存在） |

EDL 窗由 Goal `t_ms ± pad`（约 −12s/+10s）与记分牌锚点推出，**不是**因果 JSON 内嵌片段列表。

---

## 2. 8.31 全场离线推理审计

### 实际 A/B 路径（非 gold_clips）

冻结：

```text
v2_strip_reinfer → AlgoStripAdapter.predict(full timeline)
  mode=reinfer_A_original, profile=production, use_llm=false
```

产物：

- B: `/data2/lpy1/_story_va_outputs/v2/cross_match_g1/B_osasuna_celta/strip_reinfer/strip_A_original.json`（**65** 链 / **663** 事件）  
- A: `…/A_uae_oman/strip_reinfer/strip_A_original.json`（**79** / **749**）

`events_to_timeline` 对本两场 **0 drop**。窗口/截断：`pre_ms=120s`, `post_ms=60s`, `window_ms=180s`, **`max_events=12`/段**, margin/IoU 去重——是候选压缩，**不是**「没扫全场时间线」。  
全场 event_id 覆盖仍极高（≈99.7%），说明瓶颈在 **类型语义（无 Goal）**，不是流式截断漏扫。

`reports/strip_dump/*` 的 `gold_clips` **不是**本路径，且被 V2/V3 provenance 拒绝。

### 类别与进球覆盖

| Match | special | danger | correction | **outcome** | raw Goal 类型 |
|-------|---------|--------|------------|-------------|---------------|
| B | 47 | 17 | 1 | **0** | **0** |
| A | 43 | 34 | 2 | **0** | **0** |

比分单球增量（raw `Score_Recognition`，非 gold）：B **5**、A **3** → 全部记为 `unresolved_goal_action`（无 Goal 动作秒）。

---

## 3. V1 兼容生成器（V3 适配层）

`v1_causal_adapter.strip_chains_to_v1_causal`：

- 输入：冻结 strip + raw events **only**  
- 输出：`schema_version=1.0-min` 的 `auto_v1_compatible_causal.json`  
- 映射：outcome/danger/… → 结果链/险情链/…；detector 英文类型 → 中文（**不**映射出 `进球`）  
- 保留：`event_id`、预测 `template_id`/`strip_clip_id`、`t0_ms/t1_ms`、证据来源  
- 比分演化写入 `v3_adapter.score_transitions[]`，`goal_action_sec=null`，`status=unresolved_goal_action`  
- **拒绝** human causal / `gold_clips` 充当 strip 输入  
- 8.31 原始 strip **原样保留**在 V2 路径；补全只在 V3 适配层

---

## 4. 原版 V1 对照运行（同场 events）

命令：`python -m story_video_agent_v3.v1_parity_cli …`

| | B human（对照） | B auto | A human | A auto |
|--|-----------------|--------|---------|--------|
| 故事进球数 | 3 | **0** | 3 | **0** |
| Compose 进球动作窗 | 有（如 3121–3143, 5645–5667, 6779–6801） | **null / missing** | 有 | **null / missing** |
| 记分牌锚点 | 有 | 有 | 有 | 有 |
| 蓄力/buildup | 有 | 有 | 有 | 有 |

**V1 为何能选对关键进球：**  
人工因果提供了与记分牌匹配的 Goal `t_ms`（标注层）。Compose 的 `merge_causal_live_goals` 用这些时间切 `*_goal_action`。

**V3/自动链为何是 unresolved 占位：**  
适配后链内 **没有** Goal 终端 → 故事事件只剩射门/扑救/任意球等 → Compose 只能落 `*_scoreboard_anchor`，`opponent_opening_goal_action` / `equalizer_goal_action` / `go_ahead_goal_action` 的 media 为 **null**。

**不是**「忘了跑 8.31」；**不是**「V1 Schema 顶层字段缺失」为主因；**是**「检测事件 + 8.31 模板空间缺少进球结果链」。视频定位缺失是下一层问题（即便有 Goal `t_ms`，仍需首次 LIVE / 禁回放）。

注意：原版 V1 human compose 仍会产出 `*_replay_supplement`（`is_replay=true`）。按本阶段最终视频约束，这些 **不得**进入 V3 正式成片；自动路径目前连 live goal_action 都没有，更不能 `render_ready`。

---

## 5. 瓶颈归类

| 假设 | 结论 |
|------|------|
| 8.31 漏检全场事件 | **否**（ID 覆盖 ≈99.7%） |
| 事件输入信息不足 | **是** — 无 Goal 类型 / 无进球动作时刻 |
| V1 Schema 适配缺失 | **次要** — 非 Goal 字段已可对齐；缺的是 Goal 语义内容 |
| 视频定位缺失 | **后续必要**，但当前连 Goal `t_ms` 输入都没有 |
| 把人工进球时间抄给 V3 | **禁止**（已遵守） |

---

## 6. 最终视频约束（本阶段）

- 仅首次 LIVE 可进正式 EDL；禁慢动作/多机位回放。  
- 自动因果 + stock V1 规划 **对齐实验完成**；素材未经回放排除 → **`render_ready=false`**。  
- P4 逐球付费 VLM 核验本阶段 **暂停**。

---

## 7. 下一步（不新建故事框架）

1. 在 **不读 gold Goal** 的前提下，从 raw 时间线 + 比分演化 +（可选）已有首次 LIVE 定位，研究如何为单球增量提出 **候选 Goal `t_ms`（unverified）**，再喂回 V1 兼容链。  
2. 任何候选必须过首次 LIVE / 禁回放门禁后才能进正式 EDL。  
3. 继续冻结 8.31；只扩展 V3 适配与证据层。

---

## 复现

```bash
cd /data2/lpy1/worktrees/migu-story-va-v3-plan2
export PYTHONPATH=10.27scasual_chain/algo
python3 -m story_video_agent_v3.v1_parity_cli \
  --events 10.27scasual_chain/data/交付_out/<match>.json \
  --strip /data2/lpy1/_story_va_outputs/v2/cross_match_g1/<A|B>/strip_reinfer/strip_A_original.json \
  --human-causal 10.27scasual_chain/data/交付_out/<match>_causal.json \
  --out-dir /data2/lpy1/_story_va_outputs/v3/plan2/v1_parity_<tag> \
  --match-id … --video-name …
```
