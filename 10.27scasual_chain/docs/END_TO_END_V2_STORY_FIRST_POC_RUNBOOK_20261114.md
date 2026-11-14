# 端到端 v2 — Story-First POC 工程运行说明（2026-11-14）

## 版本与责任

- v1 冻结：story-va-e2e-v1-frozen-20261114，方案备份文件 END_TO_END_V1_V2_SCHEME_BACKUP_20261114.md；不再开发。
- v2 开发：story-va-e2e-v2-story-first-20261114，独立增量模块 story_first_hypotheses.py + story_first_poc_cli.py。
- 代码由 ChatGPT 直接提交到 v2 分支；Cursor 只负责服务器路径确认、拉取代码、pytest、零 HTTP 执行及返回真实结果。
- v2 此时是 **P0 实验性实现**，不是已验证的端到端新版，更不是已验证的叙事质量改进。

## 模型合同（以已经交给 Cursor 的同一服务为准）

- 模型目标：**DeepSeek-V4.1-Flash**，文本故事生成，不开启 thinking。
- **复用旧 DeepSeek V4 Pro / Qwen VL 的共享服务和鉴权**，由项目原有 `story_video_agent.api_provider.load_endpoint_configs()["planner"]` 读取 `STORY_LLM_BASE_URL` / `STORY_LLM_API_KEY`（或原本已支持的 `OPENAI_*` 回退）。`STORY_VLM_*` 保持不变。
- 不另开 `api.deepseek.com`，也不要求 `DEEPSEEK_API_KEY`。此前固定官方模型 ID `deepseek-flash` 的假设已撤销。
- **模型 ID 和请求体由共享服务的实际兼容协议决定**。将共享服务中 **DeepSeek-V4.1-Flash 对应的准确模型标识** 放在环境变量 `STORY_FIRST_LLM_MODEL`；绝不回退到旧 V4 Pro 或 Qwen。这个 ID 不是密钥。第一次使用前请 Cursor 从已有服务的模型配置核实，不猜测名称。
- 显式关闭 thinking：默认 `--disable-thinking-style thinking_object` 发 `"thinking":{"type":"disabled"}`，若该服务为 Flash 提供的是 flat 参数，则选择 `--disable-thinking-style enable_thinking_false` 发 `"enable_thinking":false`。二选一，由共享服务的真实要求选择，**不得改成不发送参数、默许思考**。
- token 参数默认继承项目已有 `STORY_PLANNER_TOKEN_PARAM`，必要时通过 `STORY_FIRST_TOKEN_PARAM` 指定为 `max_tokens` 或 `max_completion_tokens`。每轮最多 1 次 HTTP、0 重试，本地估算费用守卫 ≤0.10 USD（不是账单硬上限）。
- 默认 **零 HTTP**。真实调用必须同时指定 `--enable-real-api`、`--i-approve-budget`、`STORY_API_ENABLE=1`、共享鉴权配置和 Flash 模型 ID；当前用户只说明了配置来源，尚未授权付费实验。
- 为避免真实付费前误调用，使用 `--check-provider-config-only` 执行本地请求体预检（**0 HTTP**）。此检查只验证代码组装与本地配置，不能证明远端服务确实接受该模型名或 thinking 格式。

不应混淆：模型提供商的官方直接 API 文档 != 当前第三方/代理共享服务的模型路由定义。

## 先做服务器非 Git 数据备份

在仓库下（只示意变量，替换为服务器实际上存在的文件）：

    git fetch origin
    git switch story-va-e2e-v2-story-first-20261114
    git pull --ff-only
    cd 10.27scasual_chain
    export P14_RUN=/tmp/lpy1_v3a_p14_cv_integration_20261113/run
    find "$P14_RUN" -type f \( -iname '*enriched*json' -o -iname '*events*json' \) | head -40
    export P14_EVENTS=/实际核对存在的补充原子事件文件.json
    export E2E_BACKUP_ROOT=/安全持久化目录/e2e_v1_v2_20261114
    export SRC_MP4='/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4'
    bash docs/backup_e2e_v1_v2_p14_assets_20261114.sh

必须使用实际核验的 P14_EVENTS 路径，不能把 source 原始 JSON 当作人工补充事件替代。
备份脚本复制原子事件、V3-R EDL、可用的 story_plan 与 94s story_clean.mp4，并写 SHA256 manifest。
源比赛 MP4 不复制，提供 SRC_MP4 时计算 SHA256 记录外部文件绑定。若源视频未提供，manifest 不能宣称视频已备份。
若目标目录已经存在，脚本拒绝覆盖。备份完成后仍需验证备份目标是真实持久磁盘（不能放在临时目录）。

## 零付费测试与输入准备

在同一个 v2 分支中执行：

    export P14_EVENTS=/经核验的补充原子事件文件.json
    export STORY_FIRST_OUT=/tmp/lpy1_story_first_v2_prepared_20261114
    bash docs/run_e2e_v2_story_first_poc_20261114.sh

该脚本将运行：
1. pytest -q tests/test_v3a_story_first_poc.py；
2. Story-First CLI 的默认 prepared-only 模式；
3. 断言 HTTP=0、EDL 未改、首播直播未认证、没有冒充真实 LLM 故事。

成功时输出：
- prepared_story_input.json：故事锚点、原子事件、绑定的 source PTS、caption 观察目标；
- llm_input.json：将来提交 DeepSeek 的文本请求，含 non-thinking 合同；
- event_only_baseline.json：事件时间序列及事件分数排序对照，尚非同预算 LLM 对照；
- story_hypotheses.json：当前为空，AWAITING_LLM，不是模型已经生成故事；
- hypothesis_evidence_matrix.json；
- observation_plan.json：候选 probe 池，当前无已批准故事观察动作；
- hypothesis_generation_audit.json：输入 SHA、事件覆盖、0 HTTP 与证据状态。

### 2026-11-14 POC 工程反馈与输入覆盖修正

服务器报告：P14 有效原子事件 879 条；两锚点之间 530 条（媒体 PTS [1347.123, 6436.924]）。旧版仅向 LLM 展示 240 条详细事件，未充分提示另外 290 条，误伤长程叙事探索。

v2 已调整为：
- **全量 530 条紧凑事件索引**：事件 ID、源 PTS、事件类型、短评论和元数据分数均进入生成提示；不得将 240 条误认为全部事实。
- **240 条详细上下文**：时序覆盖 + 稀有事件类型优先的可审计选样。稀有仅是候选优先级，不是因果推断。
- **所有可用事件 probe**：已标注为 REPLAY 或慢动作的不生成源镜头观察候选；尚未验证 FIRST_LIVE 的一律 UNRESOLVED。
- **真实空档统计**：从完整的 530 条时间线计算，不使用被抽样的 240 条人为制造长间隔。
- **模型上下文审计**：在 `hypothesis_generation_audit.json` 中记录 `prompt_coverage`（输入字符、UTF-8 字节数、全量目录覆盖数）；不是精确 token 计数。
- **模型输出边界**：可以引用全量索引里的真实事件 ID，但仅有紧凑标签的事件必须明确请求视频补证；不能据此确认长程因果或可剪性。

下一次零 HTTP 运行务必指定**新的空输出目录**，防止覆盖上次已保存的实验报告。返回 `prompt_coverage`、有效事件类型统计、`counts`、`pytest` 全部结果。**此版本尚未执行真实模型，因此故事假设仍为空。**

禁止复用旧 180s 固定窗口脚本声称它代表 Story-First 方案。
禁止将 HUMAN_ATOM_ENRICHED_DEV 用作 raw-only benchmark 结果。

### 可选：沿用共享服务做零 HTTP 的 Flash 模型预检

请先在 Cursor 的服务器执行环境中沿用之前的安全密钥加载方式，只设置非机密的 Flash 模型 ID（实际服务模型目录须核实）：

    export STORY_FIRST_LLM_MODEL='在现有共享服务核实到的Flash模型ID'
    export PYTHONPATH="$PWD/algo"
    export STORY_API_ENABLE=0
    python -m story_video_agent_v3.story_first_poc_cli \
      --edl "$P14_EDL" --events "$P14_EVENTS" \
      --out-dir /tmp/lpy1_story_first_gateway_preflight_20261114 \
      --check-provider-config-only

如果当前服务使用 `enable_thinking=false` 而不是 `thinking:{type:disabled}`，再加 `--disable-thinking-style enable_thinking_false`，不能同时发送两个格式。验证请求体配置是否为目标 Flash 模型、thinking 显式关闭、没有回退到 V4 Pro、没有输出密钥、HTTP=0。**不得在不确认 Flash 模型 ID / 关闭思考格式的情况下发起真实模型请求。**

## 下一阶段（目前只设计，不执行）

1. 用户明确批准小额真实模型实验后，才运行 DeepSeek-Flash non-thinking；输入仍为 frozen V3-R 及补充事件，输出最多 5 条待证伪的故事假设。
2. 比较故事是否可区分、是否引用真实事件、是否明确缺证；再决定是否运行 VLM Caption。
3. 任何插入候选必须独立通过 V3-A 原有真实视频、source SHA/PTS、FIRST_LIVE、无 replay/慢动作、EDL 单调、受保护进球与故事质量门禁。
4. 如果 Story-First 无法带来新增有效证据，考虑事件图、粗排细排或短程预测因果链备选，不捏造提升。

## Cursor 回传要求

只回传真实工程执行结果，不让 Cursor 重新设计或修改算法：
- HEAD commit SHA、pytest passed/failed 完整摘要；
- P14_EDL、P14_EVENTS、P14_STORY 的真实路径以及各自 SHA256；
- backup_manifest.json、prepared_story_input.json、hypothesis_generation_audit.json、observation_plan.json；
- 如有错误，原始 Traceback 与最小复现，不在 Cursor 侧自行“调整启发式修复”。

## 2026-11-14 Run01 失败诊断后的 Stage-1 Compact Skeleton 协议

已证实 Run01：DeepSeek-V4.1-Flash non-thinking，一次 HTTP，prompt=64108 tokens，
completion=3200 tokens，reasoning=0，finish_reason=length，
估算支出 $0.011536，`FAILED_NO_PROMOTION`。旧代码没有落盘模型原文，
诊断结果 `RAW_RESPONSE_UNAVAILABLE`；不能断言模型究竟输出了几条故事。

修复策略（代码直接提交 v2）：
1. **只修改 Stage-1 输出形态，不改变事件输入覆盖和当前 source interval**。保留 530 条紧凑事件全索引和最多 240 条详细信息。
2. 模型首次只返回短故事假设骨架：H-ID、mechanism_key、简短假设描述、2–4 个事件 ID、一条长程关系、一条可证伪条件、一个视频观察 query。禁止额外的中间状态列表、长篇解释与 EDL 修改建议。
3. 不强迫凑满候选数：证据不够返回空列表。推荐下一次仅请求 `--max-hypotheses 2`，保持输出上限 `--max-completion-tokens 3200`，不要未经审计增加上限。
4. 解析仍接受旧版含扩展字段 JSON（兼容离线基线），但不接受空关系、空观察问题、空证伪条件或空故事描述。
5. 响应在检查 `finish_reason` **之前**先落盘 `llm_raw_response.txt`，即使因长度截断也保存诊断原文；该内容仍为 `FAILED_NO_PROMOTION`，不得作为有效假设。
6. `generation_protocol=STAGE1_COMPACT_SKELETON_V1` 写入 audit 和 llm_input，方便与 Run01 区分。
7. Stage-2 继续采用真实事件/视频证据交叉核验；未提供 FIRST_LIVE 证明时 observation plan 不具备 EDL 合法剪辑资格。

**下一个执行合同仅为零 HTTP**：拉取代码、跑完整测试、用上次已核验的
P14 资产、`--max-hypotheses 2`、独立新输出目录
`/tmp/lpy1_story_first_v2_compact_preflight_20261114`
运行 prepared-only，重新使用官方兼容 tokenizer 测量新 `llm_input.json`
内两条 messages 的实际 tokens 并记录 SHA/字节数。即使改变了系统提示，
**绝对不能**沿用 Run01 的 64108 作为这次实测值。
确认请求体与先前的共享 API 配置一致；不得调用真实 LLM/VLM。
真实下一次付费 Run02 必须另行获得用户批准，不能自行触发。

