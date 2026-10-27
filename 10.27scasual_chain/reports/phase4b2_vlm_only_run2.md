# Phase 4B.2 第二次真实 VLM-only 联调报告

**分支**: `story-va-phase2c` @ `331eb7d`（本报告提交将叠在其后）  
**环境**: 无沙箱（DNS/TLS 正常）· Paratera · **Qwen3.6-Plus** · 未调 Planner  
**状态**: **已完成并停止** · 无第二轮 · 无 go_ahead 搜索

## 一句话结论

网络与 Chat Completions **均成功**；Qwen 返回了合法结构化观察，并描述了射门/进球/庆祝（记分牌仍显示 0–1）；候选 equalizer 窗被调整到 **3059.903–3071.903**，但 **仅 observation_only**，`render_ready=false`，**不能**当作已核验进球事实。

## 分层验收

| 层次 | 结果 |
|------|------|
| 1. 网络请求 | **成功** · HTTP attempts=**1**/3 · `http_status=200` · 无 URLError |
| 2. Chat Completions | **成功** · `provider_mode=real` · `real_ok=1` |
| 3. 结构化视觉观察 | **合法** · `normalized_ok=true` · actions=`shot,goal,celebration,scoreboard` |
| 4. 场景语义 | 描述克罗地亚射门扳平+滑跪庆祝；记分牌 overlay 仍 0–1（模型注明转播延迟） |
| 5. frame_id / 媒体时间 | 三帧绑定正确：3059.96 / **3065.9** / 3071.86（含中心） |
| 6. 定位改善 | 候选窗自 3061.903–3073.903 → **3059.903–3071.903**（与搜索窗对齐）；**未** promote 成片 |

## 用量

| 项 | 值 |
|----|-----|
| HTTP | **1**（远低于上限 3） |
| prompt / completion / total tokens | 6427 / **3195** / 9622 |
| 配置 completion 上限 | **256**（请求侧已设；**服务商用量回报未遵守**，需后续跟进，本轮未加额度重跑） |
| est_cost_usd_real | **≈ $0.00288**（估算软顶 $0.10；≠ 账单） |
| 耗时 | ≈82.2s |

## 抽帧

| frame_id | requested | actual | 备注 |
|----------|-----------|--------|------|
| f_0000_3059953 | 3059.953 | 3059.96 | 窗起点 |
| f_0001_3065903 | 3065.903 | **3065.9** | **中心**；禁区射门瞬间（人工可见） |
| f_0002_3071853 | 3071.853 | 3071.86 | 窗终点；滑跪/倒地 |

## 模型观察摘要（脱敏）

- **story_relation**: Croatia player takes a shot and scores an equalizer goal, followed by a celebration slide, while the scoreboard overlay has not yet updated.
- **notes**: Frame1 总览比分 0–1；Frame2 白红球衣射门；Frame3 同队员滑跪庆祝；记分牌仍 0–1。
- **labels**: goal, shot, celebration, scoreboard · confidence 0.95 · `observation_only=true` · `fact_verified=false`

## 门禁

- go_ahead_goal: **unresolved**（pending / media_in=null / blocked）
- `render_ready=false` · render_ready_edl 空
- equalizer: `candidate_only` + `phase4a_observation_unverified` 等 blocking_reasons

## 对比

| | Mock | Run1（失败） | **Run2（本次）** |
|--|------|--------------|------------------|
| 网络 | 无 | URLError×3 / DNS | **OK** |
| provider | mock | degraded | **real** |
| 标签 | 伪 goal/shot | uncertain | goal/shot/celebration/scoreboard |
| 中心帧 | 无（仅两端） | 无有效观察 | **有 3065.9s** |
| 窗调整 | 有（不可信） | 无 | 有（观察驱动，仍未核验） |
| 费用估算 | 0 | 0 | ≈$0.00288 |

## 产物路径（本地）

- `_local_render/phase4b_real_vlm2/phase4a_experiment_report.json`
- `_local_render/phase4b_real_vlm2/croatia_preview_v2.mp4`
- `_local_render/phase4b_real_vlm2/review_v2/contact_sheet.jpg`
- `_local_render/phase4b_real_vlm2/frames/*.jpg`（**不提交**）
- 仓库报告：`reports/phase4b2_*.md/json`

## 下一步建议（不自动执行）

1. 跟进 Paratera 对 `max_tokens=256` 未生效（回报 3195 completion）——确认参数名/思维链计费字段。  
2. 若需更紧镜头：可在 3065.9±2s 再授权一小轮（仍 HTTP≤3），人工/独立核验后再谈 `render_ready`。  
3. **禁止**用本次标签直接签发成片；go_ahead 仍未搜。

**本次实验结束。**
