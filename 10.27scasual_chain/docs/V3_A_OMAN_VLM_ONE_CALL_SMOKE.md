# V3-A 阿联酋 vs 阿曼：单次真实 Qwen VLM 视频观察

**授权范围**：用户已批准一次真实 Qwen VLM 最小测试；不是批准完整 3 轮或任何第二次调用。服务器端需要由 Cursor 执行；本 GitHub 提交本身不会触发 API。

前置已验证（用户提供的服务器报告）：

- A_planner_smoke_20261105_202431/planner_smoke.json：Planner real、有效 JSON、4 条 validated video tool requests、1 次 HTTP。
- fresh E2E：closed_loop_A_uae_oman/fresh_e2e_A_real_20261105_183136。
- 之前 VLM=0，因 Planner thinking 耗尽输出预算；本次不再调用 Planner。

## 0. 隔离

在现有独立 worktree migu-v3a-planner-diag-A 中获取 story-va-v3a-fresh-e2e-a-20261105 最新提交。禁止修改冻结分支、原 fresh run、历史 P1 和 Planner smoke 目录。

脚本：10.27scasual_chain/scripts/smoke_v3a_A_vlm.py

测试：10.27scasual_chain/tests/test_v3a_A_vlm_smoke.py

先加载服务器已有 Qwen API 安全环境变量，不要打印或提交 Key。必须显式设置 STORY_VLM_MODEL 且名称能识别为 Qwen（包含 qwen，不区分大小写）；否则预检失败，避免意外继承 DeepSeek Planner 模型。

## 1. 零付费测试与预检

~~~bash
export PYTHONPATH="$PWD/10.27scasual_chain/algo"
python -m unittest discover -s 10.27scasual_chain/tests -p 'test_v3a_A_vlm_smoke.py' -v
python -m unittest discover -s 10.27scasual_chain/tests -p 'test_v3a_A_planner_diagnostic.py' -v

BASE="/data2/lpy1/_story_va_outputs/v3/plan2"
python 10.27scasual_chain/scripts/smoke_v3a_A_vlm.py \
  --out-dir "$BASE/A_vlm_preflight_$(date +%Y%m%d_%H%M%S)"
~~~

不加 --one-call 时绝不发 HTTP。检查 vlm_smoke_summary.json 与 preflight.json：

- PREFLIGHT_ONLY_NO_HTTP，http_attempts=0
- Planner smoke 状态 PLANNER_READY_FOR_VLM
- 从 4 条已验证请求中选择 **一个进球锚点**，拒绝 buildup/无锚点请求
- 使用 fresh planner_context.json 的 trusted anchors 和 00_input_manifest.json 的**原始 MP4**
- VLM request profile video_rsi，thinking={type:disabled}，max_tokens=2048，stream=false
- max_http_attempts=1、max_retries=0、预估成本上限 USD 0.03（非账单硬上限）
- 在进程内覆盖服务器遗留的 256 token 上限；不修改 env 文件

## 2. 单次真实 Qwen VLM（已获本次授权）

仅当测试与预检全部通过，执行**一次**：

~~~bash
python 10.27scasual_chain/scripts/smoke_v3a_A_vlm.py \
  --out-dir "$BASE/A_vlm_smoke_$(date +%Y%m%d_%H%M%S)" \
  --one-call --i-approve-one-call
~~~

脚本直接调用现有 _observe_one_window()，抽取最多 4 张视频帧，绑定程序记录的 frame_id、actual_media_sec、pts_status，然后调用 Qwen VLM。**不要调用 run_vlm_observations()，它有多窗口和 followup 逻辑，会扩大 API 调用次数。**

- Planner/Verifier HTTP=0；VLM HTTP 最多 1 次，重试 0；不自动二次付费重跑
- 不使用历史 P1 EDL；不修改候选 EDL，不渲染 MP4
- 不使用回放补证；单窗负结果不代表全场没有进球
- 输出中 fact_verified=false、first_live_verified=false，无论模型置信度多高

## 3. 结果与门禁

在新目录检查：

- preflight.json：脱敏 API 配置、所选 anchor/window、原始 MP4 路径与大小
- observation.json：抽取帧的 frame_id、真实 PTS、模型输出与 API usage
- evidence_assessment.json：模型是否真实、引用的 frame IDs 是否属于本次输入、是否有真实 PTS、是否包含可见语义、shot/net/replay 状态
- vlm_smoke_summary.json：HTTP attempts、token、估费、错误和最终状态

门禁：

- VLM_OBSERVATION_WITH_PTS：真实 VLM JSON + 非空视觉语义 + 有效 frame_id 引用 + 引用帧均有实际 PTS；**仅证明单窗观察链路可用**。
- VLM_REAL_BUT_EVIDENCE_INCOMPLETE：真实 VLM 调用返回，但帧引用/PTS/语义不足。
- VLM_NOT_READY：未形成可用真实观察。
- VLM_DIAGNOSTIC_FAILED：预检/执行错误。

汇报 model、HTTP 数、token、估费、选中 anchor/window、帧 PTS、VLM 原始语义摘要、shot/net/live_or_replay 及门禁状态。即使通过，也不得声称 FIRST_LIVE_VERIFIED 或 Agent 已完成修订。**运行一次后停止，等待新的完整闭环授权。**

本次会话仅提交 GitHub 脚本、测试与说明，未访问服务器或执行真实 VLM。
