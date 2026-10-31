# 咪咕足球故事链 V2 — G1 T01 跨比赛最小改造与零付费干跑（Cursor 执行）

> **给 Cursor Agent：请读取本文件并执行。G1 的目标是将 G0 已发现的 P0 真正修入生产调用路径，然后用 A/B 两场新足球视频检验同一类 T01 逆风翻盘的跨比赛适配。**
>
> **G1 不等于跨场成片交付**：不调用付费 DeepSeek/Qwen，不进行正式长视频渲染，不把“有比分变化”称为“已视频验证进球”；所有输出 `render_ready=false`。完成后提交/推送实际代码、测试、报告与证据。

## 0. 前置、保护与环境

- 仓库 `LinPengyue/migu-causal-chain`；工作分支 `story-va-video-driven`。先 `git fetch && git pull --ff-only`，核对 `git status` 和实际 HEAD；编写时 G0 HEAD `a5072f9b4141fdc2702aaaca68ca95e1ec7eca61`，以执行时 HEAD 为准。不得 reset/force-push、不得改 `main`。
- 必读同目录：`STORY_VA_V2_G0_DECISION.md`、`STORY_VA_V2_G0_MIGRATION_BLOCKERS.md`、`STORY_VA_V2_G0_ARCHITECTURE_AUDIT.md`、`STORY_VA_V2_G0_INTERFACE_CONTRACT.md`、`STORY_VA_V2_G0_MATCH_MATRIX.md`。
- 冻结 `story-va-v1.0-structured-baseline`、独立 `/data2/lpy1/causal-chain2/8.31causal_chain/` 源码、克罗地亚 R2.9 原始产物及其门禁（`render_ready=false; visual_qc_pass=false; blocked_source_corruption=true` 仅是克罗地亚的源损坏，不要传播到 A/B）。
- V2 允许输入：当前比赛 MP4、对应原始 events.json、由独立 8.31 **非 gold** 自动推理的 predicted strips、同比赛经 provenance 验证的历史 V2 视频观察。禁止：`*_causal.json`、`strip_gold*`、`highlight_gold*`、V1 EDL/进球时间/人工角色/旧 Phase5 输出成为输入或缓存。
- **付费 API / token = 0**。默认关闭 real / VLM / LLM，不打开付费密钥或自动 preflight 网络调用。可执行本地零付费单测、结构测试、文件哈希和 A/B 离线预测链（不改 8.31），**不产生新跨场正式 MP4**。全场本地算法运行前记录实际输入、费用/算力预算、输出目录；如缺必要输入或预算无法满足，保守 STOP，不伪造通过。

## 1. G1.1 — 把 G0 隔离 helper 真正接入生产调用链（P0）

G0 新增 `v2_g0_cross_match_preflight.py` 和 11 项合成测试，但这些 helper **尚不能替代 CLI 的实跑防护**。G1 必须修改实际跨场入口或新增明确的 generic entrypoint；不能只新增另一份未被调用的 helper。

1. **强制显式比赛身份**：`--match-id` / `--video` / `--events` / `--out-dir`；新入口不允许默认回退克罗地亚 `DEFAULT_R22`、`/tmp/croatia_vlm_probe` 或 R2.2 历史已验证进球。必须校验 events 内的 match_id 与 CLI 身份一致（规范化规则要可审计，不能靠模糊 substring）。
2. **输入门禁**：在任何 JSON 载入/副作用前拒绝 gold/causal 文件路径或顶层角色/人工关系字段；包括通过别名路径、目录中的 gold 文件误传的情况。正常原始事件字段须保留；不要把 `human_corrected` 误当作可以加载 `*_causal.json`。记录拒绝原因。
3. **provenance**：`match_id + video_sha256 + events_sha256 + strip_provenance` 必须校验；完整文件 SHA-256 使用分块流式读取并复用可信计算结果（5GB 视频不应每步骤重复全量哈希）。strip_provenance 要绑定真实 run id、输入 events hash、8.31 算法版本与自动预测类型，而不是任意字符串 `algo_predicted:x` 就信任。无法证明来源时拒绝缓存/自动补证。
4. **verify cache 原子绑定**：不只校验目录，还必须对每个 `verify_{event_id}`、VLM 帧引用、源 PTS、证据内容和当前视频/事件绑定信息进行检查；event_id 在不同比赛碰撞不能放行。旧克罗地亚缓存没有新 provenance 时 **fail closed**；不得自动“继承”或静默填补字段骗过检查。
5. **不要破坏克罗地亚回归**：保留旧 CLI 的历史行为但禁止新跨场误用；新增 generic CLI 或在旧 CLI 对 `match_id` 进行强保护，清楚区分“legacy Croatia-only”与“cross-match generic”。

**验收**：实际入口在不同 match_id / 不同 video hash / 不同 events hash / 不同 strip run 下全部拒绝串场缓存；运行时无法从禁用文件读入人工因果；错误必须带原因且 `render_ready=false`。补充运行级单测，不能只断言 helper 返回值。

## 2. G1.2 — 修 T01 末段逆转选择（P0）

- 新增或扩展可复用的 `last_deficit_arc` 分析，不是写死 A/B 的比分。对每支球队分别追踪**落后→扳平→反超**，允许一次比赛多次形成弧，支持左/右主角、进球数不定。优先选择 **最终胜者对应的最后一段有效逆转弧**；如比分末态未知、缺关键转移或存在冲突 OCR，则 `unresolved` 或显式 `partial_story`，不能强行选择。
- B 的合成轨迹 `0:0→0:1→1:1→2:1→2:2→2:3`，必须选择 **right/塞尔塔末段 2:1→2:2→2:3**，不能把 left 的 0:1→1:1→2:1 当最终 T01 主线；A `0:0→0:1→1:1→2:1` 选择 left；无逆转和最终只扳平负例不得强制 T01。
- 记分牌左右顺序须以当前比赛的可靠事件/画面元数据映射球队，未知不得编造队名。区分 `score_confirmation_sec`（比分观察时间）与真正 `goal_action_sec`（视频证据时间）。
- 输出 `selected_arc` 的 deficit/equalizer/go_ahead 对应 **状态、时间、置信理由、被放弃的其它 arc**，让 Planner/Graph 使用选中的弧；若新 API 未接入真正 Planner/Graph 数据流，报告不得写“跨场主角问题已修”。

**验收**：B 的真实 events 轨迹/负例合成 + 右侧队名映射过关；真正后续 Planner 采用所选弧，不能在报告层修好、实际 EDL 仍旧用首次落后。

## 3. G1.3 — 通用 N 球 EDL（P0）

- 新增通用数据驱动 EDL composer，不直接修改 R2.6–R2.9 克罗地亚成片逻辑。输入：当前比赛 `selected_arc`、视频已核证的关键进球（可以是 3/4/5/...，不可要求恰好 5）、预测拆条证据、Planner 选中的非进球节点、球队名称、视频长度和来源证据。
- 每个 role 基于**比分转移作用**分配，非固定 g01/g11/g21/g31/g41：`opening_deficit`、`equalizer`、`go_ahead`、可选 `extend`、合理 `buildup/context`、`resolution`。叙事五段不是“五球/五视频段”；不强塞毫无价值的拆条。
- 分清两个输出级别：
  - **structure_only 候选**：如果只有 score anchors / predicted strips / 事件候选、未视频核证关键进球，可输出 `story_plan`、`story_graph` 和 `candidate_edl` 的**未确认占位/待检索窗口**，但不得产生标为完整首次直播的 goal segment、不得标 `verified_first_live`、不得自动正式渲染；
  - **video_verified 候选**：仅真实 video-verified shot/net/live 证据完整时允许进入可渲染目标 EDL；所有 Live-Only/源损坏/最终人工审核门禁仍独立。
- 对 `no_comeback` 应输出解释和状态，不生成翻盘故事 EDL；关键进球未补证为 `unresolved` / `partial_story` 而非虚构。
- 从真实动态球队名构建标题、比赛信息与比分，不写入克罗地亚队名、3:1 源损坏区间或固定 PTS。场次错误使用旧 EDL 构建器必须被测试明确拒绝。
- `render_ready=false` 不受合成测试、结构完整、score path success 或自动 QC 影响。

**验收**：以合成 3 球 A、B 末弧、多进球扩大、0 逆转、缺 shot/net、mixed/replay、错误 PTS 越界各类单测测试**实际 composer**与入口；既保留必须进球，也不凭空发放视频核证状态。

## 4. G1.4 — A 后 B：分阶段零付费干跑（不是成片）

**Gate 0：** 1–3 步的代码和测试通过、克罗地亚 R2.9 文件/既有状态未变、input provenance 可验证后才开始 A。失败则 STOP，先报告，无须继续 B。

A **阿联酋 vs 阿曼**（核实实际绝对路径；历史 G0 矩阵已有）：
- 使用 A 的 MP4 + **A 原始 events.json**；独立 8.31 算法若缺可证明来源的 A predicted strips，可按现有只读调用方式生成 A 的预测拆条（不改 8.31 源码；不得用 A 的 `*_causal`、gold/dataset 做替代）。
- 禁止复用任何克罗地亚 R22、verify、strip、Planner memory。验证比分轨迹 `0:0→0:1→1:1→2:1`、left 主角、变量 N=3 的故事骨架，并保存每个推断/节点的来源、当前验证状态。
- A 几乎无 typed Goal：必须执行 missing-goal candidate 发现；在未启用付费视觉/无新有效缓存时 `unresolved` 是**正确且允许的安全结论**。不能为了满足测试将“score change”或旧 causal 时间写作已核证 live goal。
- 输出 A `score_path`、`selected_arc`、`missing_goal_candidates`、`predicted_strip_chains`、`story_graph`、`candidate_edl`（可保留 unresolved）、`provenance`、报告；**不渲染 MP4、不声称 QA/故事成功交付**。

**冻结 G1 通用配置/代码候选 SHA 后**，B **奥萨苏纳 vs 塞尔塔**：
- 只替换 B 的 MP4、raw events、合法的 B predicted strips 与 `match_id`，不改代码/阈值/规则；如果必须改，标记为 **B failure + new fix needed**，不能称 zero-modification transfer。
- 确保选择 **right/塞尔塔** 的 `2:1→2:2→2:3` 末段弧；其它进球可以是上下文，不强制成为所选弧内的首要三球。
- 同样列出未视频补证的节点；非 gold、无 VLM 就不升级 verified；不能借用历史 V1 跨场正例结果。
- 每个干跑输出独立目录，建议 `/data2/lpy1/_story_va_outputs/v2/cross_match_g1/{A_uae_oman,B_osasuna_celta}/`，不覆盖 R2.9 目录。统计实际耗时、CPU/GPU、输入 hashes、8.31 predicted provenance、API/token/付费（应为 0）。

**Gate 1**：A 无错场、无 gold/causal、N 球不崩、比分主角正确、unresolved 不升级 → 可以试 B。  
**Gate 2**：B 在**冻结代码**下正确选择 right 最后翻盘弧、无串场/虚构 verified → G1 “结构干跑可迁移”候选成立。没有视频核证、实测视觉 QC 和人工审片之前，**绝不能宣称完整 V2 已跨场验证成功**。

## 5. 结果汇报必须避免的两个假阳性

1. **「G0 11 单测 OK」≠真实入口已接入保护。** G1 应针对真实 CLI 读路径、cache、video、event 和 EDL 构建的集成测试提供可重复命令/记录。
2. **「A/B 比分路径匹配 + 能写出 JSON」≠进球实际定位成功。** 标记每个关键进球 `score_only` / `event_candidate` / `predicted_strip_candidate` / `video_verified`；只有最后一级可支撑可信的首次直播 goal EDL。G1 零 API 时多数点可能 unresolved，这属于真实结果，不能随意标 PASS。

## 6. 最终交付与提交

在 `10.27scasual_chain/docs/` 提交：
- `STORY_VA_V2_G1_IMPLEMENTATION_REPORT.md`：逐项修复文件、函数、真实入口 wiring、测试和异常。
- `STORY_VA_V2_G1_A_DRY_RUN.md` / `STORY_VA_V2_G1_B_DRY_RUN.md`：实际输入路径与 provenance、状态转换、真实/未验证结果、错误/STOP 原因；如果未运行 B 必须明确 `NOT_RUN`。
- `STORY_VA_V2_G1_TRANSFER_COMPARISON.md`：A/B 条件、冻结 SHA、是否零修改、迁移通过的范围、G2 视频补证与成片需要何种预算。
- 新增代码、tests、可复现零付费命令；视频/大体积缓存留服务器，不要 push GitHub。
- 维护 `render_ready=false`、不启动 G2/正式 API/成片；不改 V1/8.31/main。

最后用中文汇报 **HEAD / P0 实际修复状态 / A dry status / B dry status / 合法 strips provenance / 是否借用任何人工输入（必须无）/ unresolved goals 数 / 测试实际数量 / API=0 / commit SHA / 可读 GitHub 文件链接 / 是否建议进入 G2**。

**若证据或输入不足，允许局部完成并清楚 STOP；不要用自动补齐来制造跨场成功。**
