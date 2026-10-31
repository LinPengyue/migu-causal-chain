# 咪咕足球故事链 V2 — G0 跨比赛通用化审计与迁移准备（Cursor 执行任务）

> **任务性质：G0 仅做代码级审计、通用化方案、隔离门禁与最小非生产检查。禁止提前做 G1/G2 的跨场真实推理或成片。**
>
> **目标：** 判断现有 V2 是否能在 **T01「逆风翻盘」** 类型内，针对新足球比赛，使用 `MP4 + 原始 events.json + 独立 8.31 自动预测拆条`，在不使用人工 `*_causal.json`、`strip_gold`、人工进球时间或 V1 角色的前提下，自主识别翻盘、定位关键进球并形成 Story Graph、EDL、候选长视频。明确「可以直接复用」「仅改配置」「需要通用化改造」「缺少验证」的边界。

## 0. 仓库、基线与硬性约束

- 仓库：`LinPengyue/migu-causal-chain`；仅操作 `story-va-video-driven`，执行前 `git fetch && git pull --ff-only`，记下实际完整 HEAD 和工作树状态。编写本文时目标分支 HEAD 为 `604abbe8f42c487f5abcdd10351961b13feec073`；如果发生更新，以执行时 HEAD 为准，不 reset/force push、不改 main。
- 仅审计 `10.27scasual_chain/` 中的 V2，**V1 tag `story-va-v1.0-structured-baseline`、独立 `/data2/lpy1/causal-chain2/8.31causal_chain/`、历史 events.json 不得修改**。
- V1 历史 Phase 5 跨场测试**依赖人工因果链**，只能作为背景、候选比赛清单和离线对照，绝不可当作 V2 的已验证泛化结果；V1 `*_causal.json`、人工 `strip_gold`、V1 EDL 进球时间、预制故事角色禁止进入 V2 推理、缓存、检索、调参或自动评测预测。
- 保持克罗地亚 R2.9 的现有状态：`render_ready=false`，`visual_qc_pass=false`，`blocked_source_corruption=true`（其 3:1 源画质损坏属于单场媒体例外待处理，不应泛化为「所有新场次必然阻塞」）。
- **API/token = 0**；禁止触发 DeepSeek / Qwen / 任何付费 VLM；不得新跑正式 8.31 全场预测、全场视频推理、渲染新的跨场 MP4。仅允许零付费单元测试、静态代码追踪、CLI help、配置验证与必要的 mock/synthetic smoke。
- 当前任务只验证「T01 同类型适配」，不扩成其他故事类型，不做跨环境迁移或重新设计整个智能体。

## 1. 先画出真实代码数据流，不可只根据文件名推测

按真实函数调用、CLI 参数和输入输出 schema 逐段追溯：

```
视频 MP4 + 原始 events.json
    ↓ 事件适配 / 比分状态 / 翻盘主角识别
Missing Goal Detector + 视频候选查找/核证
    ↓ 缺失进球增强事件（仅经有效视频证据支持）
独立 8.31 自动拆条 A/B（在本任务仅审阅调用路径，不实际重跑）
    ↓ predicted strip + key events + evidence
DeepSeek 或 rule fallback 的 Story Planner
    ↓ story beats / temporal,narrative,causal links
Story Graph + 通用 EDL composer
    ↓ 渲染 + source↔render mapping
最终 MP4 Visual QC / Live-Only / deliverability gates
```

至少审计下列实现（存在变动可寻找实际对应入口）：
- `v2_event_adapter.py`, `v2_score_transitions.py`, `v2_missing_goal_detector.py`
- `v2_goal_recovery_runner.py`, `v2_strip_reinfer.py`, `v2_strip_adapter.py`
- `v2_strip_guided_runner.py`, `v2_strip_guided_r2_3_cli.py`, `v2_strip_guided_r2_3_planner.py`, `v2_strip_guided_r2_3_key_events.py`
- `v2_strip_guided_r2_6_build_edl.py`, `v2_strip_guided_r2_8_build_edl.py`, `v2_strip_guided_r2_9_build_edl.py`
- `v2_strip_guided_r2_7_render.py`, `v2_strip_guided_r2_8_visual_qc.py` 及最终 Live-Only/回放门禁。
- 各 CLI 的默认目录、`--input-source`、`--r22-dir` / `--reuse-verify-cache` / `--algo-root` 的实际数据来源。

对每个模块写 **入口函数、输入 schema、输出 schema、调用者、硬依赖、跨场风险、证据所在代码行**。对无法从代码确认的环节写 `NOT_VERIFIED`，不得把有源代码等同于真实能力已验证。

## 2. 重点找「会导致换场失败」的真实硬编码与污染

必须用全仓检索和反向调用链验证以下问题，列出确切文件+行号+代码片段+实际影响：

1. **固定五球 / 固定比分轨迹：** 已知 `v2_strip_guided_r2_6_build_edl.py` 有 `len(goals) != 5` 约束，R2.8/R2.9 EDL 含克罗地亚固定源 PTS、比分和结尾；不得将它们包装为通用 EDL。审查所有 `g01/g11/g21/g31/g41`、固定片段数、固定 `0:1→4:1`、`all_five_goals` 之类标识。
2. **跨场缓存污染：** `v2_strip_guided_r2_3_cli.py` 已知默认 `DEFAULT_R22` 指向克罗地亚历史结果；核查是否存在默认视频路径、缓存目录、strip、verified goal、Planner memory、frame ID、score anchors 不匹配仍被读取。设计强校验 `match_id + video_sha256 + events_sha256 + strip provenance`，并校验缓存绑定的媒体时间轴、完整源身份；应拒绝 mismatched/缺失 provenance，不要自动 fallback 到克罗地亚。
3. **数据权限：** 区分 `events.json` 的 `human_corrected` 与 `upstream_detected` 接口：允许真实原始事件字段，但任何人工 causal/story roles/gold 必须被严格拒绝；明确事件预处理白名单与是否存在“人工修正事件”隐含故事标注泄漏风险。
4. **T01 识别通用性：** 不仅支持开场即 0:1 后 4:1，还要支持“中途落后→扳平→反超”“右侧球队翻盘”“多次互换领先但最终最后一段翻盘”“无翻盘→no_comeback”“仅扳平未反超→non-comeback/partial（按当前业务定义）”。不得把五段叙事角色误读为恰好五球/五片段。
5. **缺失进球恢复：** 原始 events 可能没有 Goal、比分记在 Throw_in/Pass/Foul 等事件，检测器是否能覆盖；score confirmation 只是上界，不代表进球动作时间；不能因为 8.31 没有 outcome 就否定 video-verified goal；不能跨 probe 拼 shot+net。
6. **Live-Only/视觉证据：** 正确使用 REPLAY 标志、视频连续性及可信比分时序，mixed/ambiguous 必须保守；Live 台标非充要证据；新场次不能复用克罗地亚的源花屏白名单/PTS 例外。
7. **叙事选择：** 是否固定 2–4 条非进球 strip、在无合适铺垫时能否合理略去、是否会把所有 goal 强塞某个 beat、temporal/narrative/causal 是否有严格证据门槛；不同比分数量和多次领先的故事主角逻辑是否正确。
8. **渲染/产物：** 同媒体时间轴与源↔成片 PTS 映射、动态标题球队名、比分显示、结尾、音画处理、失败门禁（`render_ready=false` 直到用户审核）、完整 Clean/QC、`story_summary.md`、`story_graph.json`。

**输出 P0/P1/P2 风险分级**：
- P0：跨场可能产生错误进球、串场缓存、读取人工真值、错误翻盘主角、错把回放当直播、固定五球崩溃、无翻盘仍渲染；
- P1：可运行但故事弱、镜头不自然、证据追踪不完整、QC 漏检；
- P2：不影响迁移正确性的展示/风格问题。
每项写可复现最小场景和最小通用修法，**禁止仅按文件名猜测**。

## 3. 建议的首批跨场测试矩阵（G0 只盘点，不实际运行）

沿用历史 `reports/phase5_dataset_inventory.md` 与 `reports/phase5_generalization_evaluation.md` 作**历史参考而非 V2 成功证据**，确认文件当前是否存在（`test -f`、`ffprobe` 的元数据检查允许，不做整场推理）：

- **M0 开发回归：克罗地亚 vs 加拿大**：`0:1→1:1→2:1→3:1→4:1`，左侧主角、扩大优势、已知 3:1 源损坏；只作为回归参考。
- **A：阿联酋 vs 阿曼**：历史候选为 `0:1→1:1→2:1`，中途落后、无扩大优势；旧数据盘点曾记录 MP4 于 `/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4`。**待重新核查当前存在与输入类型**。
- **B：奥萨苏纳 vs 塞尔塔**：历史候选 `0:0→0:1→1:1→2:1→2:2→2:3`，最后一次逆转由右侧塞尔塔完成；历史 MP4 `/mnt/data4/migu/10月27日 25-26赛季西甲第10轮 奥萨苏纳VS塞尔塔 国语.mp4`，需核查。
- **C：法国 vs 澳大利亚**：旧盘点为上传中、未验证；若现在已有 MP4 可列为 G1 备选，**不得预先标为已测**。
- **N 负例**：无翻盘/领先方始终领先的实际有源视频，必须先确认对应 MP4 与原始事件存在；无视频的旧“卡塔尔 vs 阿联酋”**不可作为已执行的视频负例**。

**不要用历史 V1 `*_causal.json` 的事件时间或旧故事输出喂给 V2。** 只整理真实文件存在性、元数据、8.31 自动拆条可否独立生成的调用路径、预计 G1 测试目的及风险。

## 4. G0 允许的代码工作：只增“防误用”检查，不作生产重构

优先只交付报告和 schema/配置设计。若有充足依据，可新增**独立、无副作用**的测试或 preflight 验证器（新增文件，不能改变现有 V2 核心推理/EDL 输出），用合成数据检查：
- 3 球/5 球/可变球数的 T01 骨架；
- 右侧翻盘及“无翻盘”不会强制编造故事；
- 不同 `match_id` 或媒体 hash 的缓存无法混用；
- 人工 causal/story/gold 字段被拒绝；
- 无法补证关键进球时输出 `unresolved`，不伪造 verified；
- `render_ready` 不会因 synthetic PASS 或结构化检查升级。

这里的可选合成测试只能说明测试设计与校验逻辑成立，**不能直接声明 V2 泛化跑通**。如发现需修改生产代码的 P0，先写最小改造建议与拟改文件清单，不要在 G0 擅自大规模重构；留到 G1 经审阅后实施。

## 5. 必须形成的 G0 交付

仓库文档建议存入 `10.27scasual_chain/docs/`，对应生成：
1. `STORY_VA_V2_G0_ARCHITECTURE_AUDIT.md`：真实数据流/模块边界、已证实/尚未验证区分、通用功能和克罗地亚单场特例。
2. `STORY_VA_V2_G0_MIGRATION_BLOCKERS.md`：P0/P1/P2、文件/函数/行号/最小复现/修法及优先级。
3. `STORY_VA_V2_G0_MATCH_MATRIX.md`：A/B/C/N 数据现状与目标、多比分路径、视频/事件/预测 strip 文件真实可用性（缺失就写缺失）。
4. `STORY_VA_V2_G0_INTERFACE_CONTRACT.md`：建议的通用 CLI/input/output schema、缓存隔离键、T01 通用叙事角色、验证状态、质量门禁；**只做设计，不改变线上接口**。
5. `STORY_VA_V2_G0_DECISION.md`：用一句话回答「能否直接换视频」；区分「G1 前必须修的 P0」和「可暂缓的 P1」，给出**最小 G1 执行顺序**与明确 stop/go 条件。
6. 若实际新增了 preflight/tests：测试命令与输出、真实新文件列表、Git SHA；若没有新增，明确 G0 纯审计即可。

报告必须附上 `git status`、执行命令、测试结果、未执行事项、真实 API/token/费用用量，以及是否改动了生产代码。

**完成 G0 的判定标准：我们可以按文件/函数指出所有已发现跨场依赖，确认 A/B 输入可用性，知道 G1 的最小改造和验证顺序；而不是已经跑出 A/B 视频。**

## 6. 结束与推送

只在 `story-va-video-driven` 正常 commit + push（遵循项目已有自动 push 约束，不强推）；不重做克罗地亚 R2.9，不改 V1/8.31/main，不开启付费服务或真实新场推理。

在最后消息用中文简洁报告：
**HEAD / G0 核心结论 / P0 列表 / G1 最小变更方案 / A/B 数据现状 / 测试实绩 / API=0 / commit SHA / 可读文档链接**。
