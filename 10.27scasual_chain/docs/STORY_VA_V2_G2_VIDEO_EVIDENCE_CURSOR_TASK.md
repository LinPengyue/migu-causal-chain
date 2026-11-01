# V2 G2 — T01 跨比赛视频补证与 Live-Only 候选审核

**Cursor 执行任务。** 工作分支：`story-va-video-driven`；以执行时 HEAD 为准，勿覆盖他人提交。基线 G1 SHA：`9469827ffe1e0d28fc92a1a969614ec85a3266c7`。先阅读同目录 G1 的 IMPLEMENTATION / A / B / TRANSFER 四份报告。

## 目标和范围

G1 已完成结构干跑，**未完成进球视频语义核证**：A 阿联酋–阿曼 3 unresolved / 0 verified；B 奥萨苏纳–塞尔塔 5 unresolved / 0 verified。G2 应先对 A 的三段比分变化寻找真实首次直播进球证据，再于方法冻结后验证 B 的右侧末段翻盘（2:1→2:2→2:3）。**本任务仅授权零付费本地视频检索、抽帧、审查短片、测试与报告；没有付费模型或正式长视频渲染授权。** 保持 `render_ready=false`。

## 1. 先排查证据升级漏洞

`v2_generic_edl_composer._verification_level` 目前主要靠 `verification_status`、`shot_sec`、`net_sec`、`live_or_replay` 字段判断。不得让任意构造的 JSON 自动升为 video_verified。请将真实门禁接入 G2 使用的调用链：

- 匹配 `match_id`、视频 SHA256、events SHA256、合法 predicted strip provenance；
- 真实源视频帧 / 连续短片存在，有准确源 PTS、帧文件 hash、shot/net 引用；检查 `media_in≤shot≤net≤media_out`；
- 同一次首次直播的进球归属、射门、入网、比分确认有可审查依据；Replay、混合、跨窗口拼接、仅有直播台标均不能通过；
- 区分 `automated_video_verified`、`human_video_reviewed`、`pending_review`；人工审查的结果不能冒充智能体自动核验成功；
- 写集成反例：只填 verified 状态、伪造/丢失帧、错比赛、重播、倒置 PTS、越过视频长度、只有比分牌均应 fail closed。

不修改已有克罗地亚 R2.9 成片或其门禁，不修改 V1 / 独立 8.31。

## 2. A 场先完成可观看的证据包

输入以 `STORY_VA_V2_G1_A_DRY_RUN.md` 的真实路径及 `/data2/lpy1/_story_va_outputs/v2/cross_match_g1/A_uae_oman/` 为准。以 `missing_goal_candidates.json` 中的真实 `search_region`、`selected_arc.json`、预测 strips 和当前原始视频为约束；比分 0:1、1:1、2:1 的观察时间是分数确认，**不得冒充进球动作时间**。

用零付费 FFmpeg / 本地场景检索按由粗到细的方式为每个进球生成几个候选原片连续短视频，并提供：
- 每个候选的 source PTS、帧截图、帧 SHA256、输入来源/hash、比分/事件/strip 对应、候选理由与不确定性；
- `clip_source_continuous.mp4` 及人可观看的联系表；不能静默跳帧、补帧或拼回放；
- 射门、入网、庆祝与 Live/Replay 正反证清单；缺连续视频判定就标 `pending_human_video_review`，绝不填写伪造 `verified_first_live`；
- 保存搜索未命中或候选不确定的实际情况，不根据旧 V1 人工因果链指定时间。

A 的三个核心角色均有原始视频证据索引和可播放候选片时，最多标记 `G2_A_EVIDENCE_PACK_READY`，**不是 video verified**。若缺可信视频语义核验，保持 3 unresolved，并停在用户审片门槛；不要制作一条声称已完成的翻盘长片。

## 3. B 场的进入条件

只有 A 的检索/证据生成工作流可复现，通用代码和阈值已冻结，才能运行 B。B 用自身 MP4 / 原始 events / 独立预测 strip，主故事为 **右侧塞尔塔的 2:1→2:2→2:3 末段翻盘**。G1 的其它 0:1、1:1 未验证事件不得被误当成该末段的三个核心进球，若作为故事上下文也应标证据状态。

冻结后仅切换输入路径和 match_id；若必须改规则，标记 B 迁移失败/待修，不称零修改成功。新场次任何进球未确证时不正式渲染。

## 4. 禁止事项、产物与汇报

- 禁付费 DeepSeek/Qwen/API；禁用 causal/gold/V1 时间作 V2 推理或标注来源；不把 Croatia 的源花屏例外传播到 A/B。
- 禁止根据 score-only/strip-only 升级进球，禁止从静态帧推定跨帧动作已连续核实。所有实际自动语义核验必须有真实运行日志和可审查帧证据。
- 新建 `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/A_uae_oman/`，B 符合门禁再建 `B_osasuna_celta/`；不覆盖 G1 及 R2.9。
- 输出 `preflight_identity.json`、`search_plan.json`、`candidate_evidence_index.json`、帧清单、连续审查 clips、`live_replay_audit.json`、`video_semantic_verification.json`（无实审则 NOT_VERIFIED）、`G2_A_EVIDENCE_REPORT.md` 和 Gate 决策。文本简报同步仓库 docs；大型视频不 push GitHub。
- 最终报告逐角色 candidate 数量/PTS/短片路径、是否真已核验、A/B 实际执行范围、测试结果、费用=0、Git SHA、尚需用户实际观看的素材和 STOP 条件。若 B 未执行写 NOT_RUN。
- `render_ready=false`，正式长视频与付费模型等用户后续明确授权。

**完成标准：有可播放、可回溯的 A 场真实视频证据包，而不是又一份仅有比分 JSON 的“已验证成功”报告。**
