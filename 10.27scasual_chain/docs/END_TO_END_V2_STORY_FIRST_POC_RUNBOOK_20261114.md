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
