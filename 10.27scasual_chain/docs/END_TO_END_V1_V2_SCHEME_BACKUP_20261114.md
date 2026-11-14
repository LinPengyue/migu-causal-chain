# 端到端 v1 / 端到端 v2 — 方案与代码快照（2026-11-14）

## 版本基准与隔离

**共同冻结点**: `fe4c618e85786cc6197adfa886e1bad75a87d97e`，原开发分支 `story-va-v3a-p14-story-quality-20261113`。

- **端到端 v1（冻结）**：分支 `story-va-e2e-v1-frozen-20261114`；补充原子事件 + V3-R 完成原始故事 + **在本轮 Story-First 改造前的 V3-A**（原 Critic / Search / Planner / Verifier 链）。禁止把 v2 实验改动回写此分支。
- **端到端 v2（开发）**：分支 `story-va-e2e-v2-story-first-20261114`；复用同一上游补充原子事件、V3-R 故事骨架，V3-A 增加 **Story-First 假设生成 → 主动视觉证据发现 → 长程关系分析 → 故事修订**。当前先实现隔离 POC，未达到端到端验收前不替换正式主链。

Git 快照只保护已跟踪代码；服务器媒体、人工标注、独立运行产物不包含在 Git 中，须由执行方做 SHA256 校验及只读备份。仅凭备份分支不能声称外部产物已经备份成功。

## 共享上游与输入边界

1. 源比赛 JSON / MP4 和已存在的补充原子事件（包含事件 ID、源媒体时间、类别、评论等可用属性）。人工补充事件只能用于明确标注为 **HUMAN_ATOM_ENRICHED_DEV** 的研发评估；不能当成纯原始输入的 Benchmark 性能。
2. V3-R 提供初始 story plan、EDL、可核验的进球动作及叙事骨架。冻结的 P14 DEV 九段约 94.877s 原始版只作为比较基线，不改其文件。
3. V3-A 主链输入输出维持原结构与正式安全门禁。不得读取 strip_gold.json 等人工答案来生成主方法结果。

## 端到端 v1（冻结的已有流程）

补充原子事件 → V3-R 预测/构建事件和故事框架 → V3-R Story Plan / EDL / 初始成片 → V3-A Story Observe / Global Critic → 原证据搜索与 Revision Planner → EDL 安全审计 / 首播直播验证 → Candidate Cut / Dual-Video Verifier → 通过则接受，否则拒绝或 UNRESOLVED。

*状态*: 原版实现已经存在，v1 在代码层通过独立分支固定。不把未证实的 FIRST_LIVE / 剪辑增益写成 PASS。

## 端到端 v2（目标流程，分阶段落地）

补充原子事件 + 冻结 V3-R Story Plan / EDL →
**Story Hypothesis Generation（LLM）**：围绕多个故事锚点，从真实事件提出相互可区分、可证伪的多个候选故事 →
**Targeted Observation Planning**：标记罕见或有歧义的事件、长间隔、状态变化解释缺口；源 PTS 与时间区间必须由代码确定，不能由 LLM 编造 →
**Active VLM Caption & Evidence Check**：仅在必要区间采样真实视频帧，记录 source SHA、PTS、frame ID 和观察事实 →
**Long-range Relation Reasoning**：维护直接动作链、状态变化、因果假设、叙事关联、未知五种证据等级；允许反驳假设 →
**Story Incremental Revision**：只提出可验证的新增片段，不默认 trim/drop 现有良好骨架 →
**原 V3-A 安全与视频核验**：回放/慢动作禁入；FIRST_LIVE 不可由文本、事件元数据、负 pHash 搜索或比分推定；正式 EDL 仅在可核验后应用 →
Candidate Video / Quality Verification / Comparison / Release Gate。

## 当前 POC 的工程验收边界

- 第一阶段只做 **LLM 候选故事 + 观察计划**，主 CLI 的当前 V3-A 不改、正式 EDL 不改、零渲染。
- 真实文本模型为 **DeepSeek-V4.1-Flash**，复用原有 DeepSeek V4 Pro / Qwen VL 的共享服务和 `STORY_LLM_BASE_URL` / `STORY_LLM_API_KEY` 鉴权；准确模型 ID 必须从该服务核实后设置 `STORY_FIRST_LLM_MODEL`，不能自行假设是官方直接 API 的 `deepseek-flash`，也不能回退到 V4 Pro。
- 必须显式关闭 thinking（服务支持的 `thinking: {type: disabled}` 或 `enable_thinking=false` 格式二选一）。默认零 HTTP，可用 `--check-provider-config-only` 进行真实共享配置的本地预检；仍不能由此推断远程模型调用已经成功。
- 默认离线零 HTTP；真实调用需要双重显式授权 + 环境开关 + 独立限额。本次开发阶段不付费。
- 离线 fixture 用于结构测试，不等于真实 LLM 测试；VLM 和剪辑效果要等后续独立实验核验。
- 需保存 source 文件 SHA、输入事件计数、引用的 event ID、时间窗来源、输出 JSON、模型请求审计与失败原因。
- 评估 Story-First 与 chronological summary、事件重要性排序的差异，最终评估 **新增真实叙事证据和成片增益**，而非模型文字是否精彩。

## 回滚

- v1: checkout `story-va-e2e-v1-frozen-20261114`，不执行 v2 模块。
- v2: checkout `story-va-e2e-v2-story-first-20261114`，Story-First 默认 opt-in 隔离，不触碰 v1/V3-R/BEST。
- v2 尚未正式端到端放量，任何 POC 输出只标记为探索结果，不能替代正式视频证据与交付结论。
