# Story-First Stage-1 Run02 — 预注册评测方案（2026-11-14）

## 边界与待回答的问题

本阶段只回答：**给定冻结的 V3-R 故事骨架以及全长区间的人工补充原子事件，DeepSeek-V4.1-Flash 能否独立提出至少两条机制上不同、可证伪、具有新增叙事价值且值得后续视频核验的长程故事假设？**

**不得**将成功调用 API、成功解析 JSON、两条不同 mechanism_key、或构造 observation_plan 直接认定为方法成功。

Run01 历史事实：一次 HTTP，64,108 输入 tokens / 3,200 输出 tokens / 0 reasoning tokens，finish_reason=length，原文不可恢复，状态 FAILED_NO_PROMOTION。其失败不能说明故事质量，只能说明此次响应未完成。

Run02 输入仍使用 P14 同一比赛与相同 source interval，属于开发验证，不代表留出比赛泛化。

## 预注册的评判表（ChatGPT 审阅真实原文，Cursor 不作主观筛选）

对每条有效候选，分别审查：

1. **Grounding**：所有引用 ID 确实存在于输入全事件索引，event type、PTS、相对顺序、所用标签可追溯；未发明人物、比分、心理、视频观察等信息。
2. **Long range**：至少有跨时间阶段的事件关系及明确的状态/进展假设，记录首末事件 PTS 和时间跨度；不把短时相邻事件、纯时间顺序或统计共现冒充因果。
3. **Falsifiability**：明确一个可通过原视频观察支持或反驳的判别信号；probe ID 合法，已知 replay/slow motion 不可被当成可用输出镜头。未视频验证时 FIRST_LIVE=UNRESOLVED。
4. **Novelty to V3-R**：与 frozen story_plan 和现有 EDL 对照，是否提出原故事没有显式表达的**可用于叙事的**事件/结构关联；仅重复已有进球、同义改写或对原 EDL 排序不算新增。
5. **Mechanism diversity**：跨候选两两比较事实依据、关键事件、时间依赖和可证伪问题；不同 mechanism_key 或不同措辞不等于不同故事机制。

输出定性结论：
- **STAGE1_PASS**：至少两条候选全部通过 1–4 且相互通过 5；可进入 Stage-2 视频核验，但**不代表故事成立或剪辑提升**。
- **STAGE1_PARTIAL**：恰有一条具有新增叙事调查价值；不足以支持“能提出两三条不同故事”的预设目标。
- **STAGE1_FAIL**：没有满足要求的候选；或虽然 JSON 合法却只有泛泛总结/重述/共现解释。
- **STAGE1_UNRESOLVED**：输出截断、请求/JSON失败、关键证据无法取得，不能评价内容。

保留每条候选的正向与反向证据，以及不足/拒绝理由。数据集 DEV 带人工补充事件，不能声称 raw-only 泛化。

## Run02 工程安全合同

1. 不改变 V3-R、原 V3-A、EDL/BEST、v1 冻结分支或已有备份。
2. 先以 HEAD 的 compact `STAGE1_COMPACT_SKELETON_V1` 跑零 HTTP pytest 与 prepared-only；检查 530 全事件 ID/240 detail、两锚点 PTS/源 SHA，context 输出及纯文本 prompt。
3. 重新使用 DeepSeek-V4.1-Flash 官方兼容 tokenizer 测量 **本次** messages 的输入 tokens；严禁重用 Run01 64,108。
4. 网关与 thinking 参数延用上次已实证成功的 Paratera 设置，非 thinking、`max_hypotheses=2`、`max_completion_tokens=3200`。
5. **只有**零付费预检通过、预算核验成功、且具有本次一次真实 HTTP 的用户授权，才在新空目录发起**单次**调用，max_calls=1/retries=0，软费用预算 $0.10；禁止输出密钥和盲目重试。
6. API 响应内容先落盘再判断 finish_reason；length/content_filter/JSON解析失败全部 FAILED_NO_PROMOTION，不补调。
7. 回传原始 story_hypotheses、evidence_matrix、observation_plan、audit、llm_raw_response（仅去除鉴权等秘密）、适量完整 event metadata 映射与冻结 story_plan 的对照素材。
8. Stage-1 正式结论由 ChatGPT 对**真实**原文和 ID/PTS 证据审阅给出；不能用结构解析成功取代语义质量审查。

## 数据局限

Run02 仍用一场已见比赛、HUMAN_ATOM_ENRICHED_DEV 事件；最多证明该场事件条件下的候选能力。下一阶段必须增加不同赛事与模板的留出测试，并维持无回放/首次直播严格门禁。
