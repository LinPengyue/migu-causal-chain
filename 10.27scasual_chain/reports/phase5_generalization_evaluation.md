# Phase 5 Generalization Evaluation

**分支：** `story-va-phase2c`  
**通用入口：** `python -m story_video_agent.phase5_pipeline`  
**历史克罗地亚硬编码：** `phase4e1_build.py`（仅回归参考，通用入口不自动回退）  
**门禁：** `render_ready=false` · 双视频均为 `candidate_only` · 无付费 API / 无自动语义签发

数据盘点见 [`phase5_dataset_inventory.md`](phase5_dataset_inventory.md)。

---

## 1. 实现摘要

| 能力 | 状态 |
|------|------|
| 输入 video+events+causal → T01 → Story Plan | ✅ |
| 动态比分里程碑（落后/扳平/反超/扩大） | ✅ 非克罗地亚比分序列 |
| 开场/弧内失球动作优先于记分牌 | ✅ |
| 统一 delivery EDL → `story_clean.mp4` + `story_qc.mp4` | ✅ 同时间轴 |
| `story_summary.md` / `story_graph.json` / `candidate_edl.json` | ✅ 同源 Story Plan |
| 可选 `--glitch-profile`（显式传入） | ✅ 不默认套用克罗地亚花屏 |
| 真实 VLM / 付费 Planner | ❌ 未验证（已标记） |
| 独立语义核验 → `render_ready` | ❌ 未授权 |

机制修复（非场次特例）：记分牌–进球匹配窗 `180s`；进球动作窗 12+10；比分牌缩短；扩大优势 `lead_extend_*`；已占用 live 进球不复用。

---

## 2. 逐场结果

### M0 克罗地亚 vs 加拿大（回归）

| 维度 | 结果 |
|------|------|
| 故事识别 | ✅ tier=`story`，主角 left 克罗地亚 |
| 事件完整性 | ✅ 失球+扳平+反超+3:1；❌ 4:1 **live 动作缺失**（因果链无第 4 球，已记 `missing_live_goal_action:lead_extend_2`，仅有短记分牌） |
| 时间定位 | 动作窗来自事件/因果 `t_ms`，非手工进球时刻；开场 ~968、扳平 ~3054、反超 ~3512、扩大 ~6305 |
| 画面有效性 | 未跑独立 VLM；候选未语义签发 |
| 故事完整性 | 五段均有镜头；第 4 球动作补证未完成 |
| 叙事一致性 | summary / graph / EDL / 双 MP4 同源 |
| 视频质量 | 显式传入 `croatia_glitch.json` 避开已知花屏；loudnorm 预览响度 |
| 自动化 | 零手工进球时间；仅可选花屏 profile |
| 通用性 | 经通用入口；`--glitch-profile` 为克场显式参数 |
| 人工干预 | **无**针对性时间窗/队名分支 |
| 成片时长 | clean=qc=**136.44s** |
| 交付 | `_local_render/phase5/croatia/`；预览 `/data2/lpy1/_story_va_previews/phase5/croatia_*.mp4`；报告 `reports/phase5/croatia/` |

### A 阿联酋 vs 阿曼（首迁）

| 维度 | 结果 |
|------|------|
| 故事识别 | ✅ mid-deficit 翻盘；主角 left 阿联酋 |
| 事件完整性 | ✅ 失球→扳平→反超（无扩大） |
| 时间定位 | 因果 live：~1325 / ~6438 / ~6831；记分牌锚点分离 |
| 画面有效性 | 未 VLM；**待画面抽检** |
| 故事完整性 | 五段齐全 |
| 叙事一致性 | ✅ 同源 |
| 视频质量 | 无花屏 profile；H.264 源 |
| 自动化 | **零修改**（无 glitch、无场次代码） |
| 人工干预 | **无** |
| 成片时长 | **118.93s** |
| 交付 | `_local_render/phase5/uae_oman/` + `reports/phase5/uae_oman/` + previews |

**冻结点：** Match A 完成后冻结算法与配置规则，再跑 B。

### B 奥萨苏纳 vs 塞尔塔（冻结后零修改）

| 维度 | 结果 |
|------|------|
| 故事识别 | ✅ tier=`story`；主角 **right 塞尔塔维戈**（最后一次落后弧） |
| 事件完整性 | ✅ 弧内失球（2:1 落后起因）+ 扳平 2:2 + 反超 2:3 |
| 时间定位 | ~3122 / ~5646 / ~6780 |
| 画面有效性 | 未 VLM；待抽检 |
| 故事完整性 | 五段齐全；复杂多次领先/落后由 score_path 弧逻辑处理 |
| 叙事一致性 | ✅ |
| 自动化 | **冻结后零修改** |
| 人工干预 | **无** |
| 成片时长 | **118.89s** |
| 交付 | `_local_render/phase5/osasuna_celta/` + reports + previews |

### C 卡塔尔 vs 阿联酋（阻塞）

| 项 | 结果 |
|----|------|
| 视频 | ❌ `/mnt/data4/migu/` 无 MP4 |
| T01 | tier=`none`（`no_comeback`）；`--skip-render` 确认不产片 |
| 结论 | **不可作正例**；负例识别行为符合预期 |

---

## 3. 定量声明边界

- **不得**宣称独立真值上的准确率 / mAP。
- 上表为算法输出 + 结构化审查；进球画面是否含完整射门过程需人工抽检 QC 版。
- 10.21 / `story_t01` 仅上游候选，非 GT。

---

## 4. 零修改 vs 人工修正

| 场次 | 零修改成功？ | 说明 |
|------|-------------|------|
| M0 | 机制通用 + **显式**花屏 profile | 无手工进球时间；第 4 球动作因数据缺失未伪造 |
| A | ✅ 零修改 | 发现并修复通用匹配窗/复用问题后重跑 |
| B | ✅ 冻结后零修改 | 与 A 同实现 |
| C | N/A | 数据阻塞 |

A 前允许的机制修复：`DEFAULT_TIME_SLACK_SEC=180`、进球去重、`lead_extend_*`、Phase5 交付管线。  
**B/C 未再改代码。**

---

## 5. 未完成 / 阻塞

1. 真实 VLM 语义核验与 `render_ready` 签发（未授权）。
2. 克罗地亚第 4 球：因果链缺 live 进球 → 需补标注或离线视觉定位（未伪造）。
3. Match C 缺视频。
4. 三场新正例进球镜头的人工画面抽检尚未系统完成。
5. 业务版仍为候选审核样片，非正式咪咕成片授权。

---

## 6. 交付路径速查

```
reports/phase5_dataset_inventory.md
reports/phase5_generalization_evaluation.md
reports/phase5/match_profiles/croatia_glitch.json   # 可选，显式 --glitch-profile
reports/phase5/{croatia,uae_oman,osasuna_celta}/
  story_summary.md story_graph.json story_plan.json candidate_edl.json phase5_manifest.json

_local_render/phase5/{croatia,uae_oman,osasuna_celta}/story_{clean,qc}.mp4
/data2/lpy1/_story_va_previews/phase5/*.mp4
```

**验收对照：** 更换 A/B 输入、不改算法、不手工指定进球时间，系统输出完整故事链报告 + 业务/QC 长视频（候选）。C 因缺视频与非翻盘标注未纳入正例。
