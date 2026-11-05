# 阿联酋 vs 阿曼 V3-A：Planner 最小诊断（一次 API，非全链重跑）

**适用前提**：2026-11-05 A 场 fresh E2E 已完成但 degraded，Planner timeout / EMPTY_MODEL_CONTENT，VLM 0 次。用户同意先检查再进行一次低成本 Planner 冒烟，不授权全场重跑。

**目标**：查明 fresh V3-R 与历史 P1 字节一致的来源；对齐 Verifier 的 thinking=disabled 请求；只发最多 1 次真实 Planner HTTP 请求，观察是否产生有效、可验证的 video_tool_requests。

## 运行位置

使用服务器上已配置 DeepSeek/Qwen API 环境的独立 worktree，检出 story-va-v3a-fresh-e2e-a-20261105 最新提交；不要覆盖之前 d93a186 生成的目录或冻结分支。入口：

10.27scasual_chain/scripts/diagnose_v3a_A_planner.py

历史 A 场 run：

/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/fresh_e2e_A_real_20261105_183136

### 0. 零付费本地测试

~~~bash
export PYTHONPATH="$PWD/10.27scasual_chain/algo"
python -m unittest discover -s 10.27scasual_chain/tests -p 'test_v3a_A_planner_diagnostic.py' -v
python -m unittest discover -s 10.27scasual_chain/tests -p 'test_v3a_fresh_e2e.py' -v
~~~

测试失败不得进行付费调用。

### 1. 零付费溯源 + Planner 配置预检

先确保 API 环境变量已安全加载。不得打印 key；不要把环境文件提交到 Git。

~~~bash
DIAG_BASE="/data2/lpy1/_story_va_outputs/v3/plan2"
python 10.27scasual_chain/scripts/diagnose_v3a_A_planner.py \
  --out-dir "$DIAG_BASE/A_planner_preflight_20261105"
~~~

**默认不发 HTTP。** 如果目录已存在，改用新的唯一目录，不能覆盖。检查：

- provenance_audit.json：fresh V3-R、fresh V3-A、历史 raw、历史 P1 的 EDL 和 MP4 SHA256；fresh EDL 与历史 raw/P1 的逐段差异；manifest 记录的实际输入路径。
- planner_preflight.json：必须 configured=true、thinking_object_disabled=true、request_thinking_sent=true、max_retries=0、max_http_attempts=1、token_limit_sent 为实际有效上限（正常为 2048）。
- diagnostic_summary.json：status=PREFLIGHT_ONLY_NO_HTTP、real_http_executed=false。

**不要**因为哈希一致就推定缓存泄漏；同时对比历史 raw/P1 EDL、输入 SHA、代码提交及实际算法读取路径。此诊断只读历史产物，不将历史 P1 作为 Planner 输入。

### 2. 一次真实 Planner 冒烟（已获本次单次授权）

仅当测试及预检全部通过，执行：

~~~bash
python 10.27scasual_chain/scripts/diagnose_v3a_A_planner.py \
  --out-dir "$DIAG_BASE/A_planner_smoke_20261105" \
  --one-call --i-approve-one-call
~~~

约束由代码强制：

- **最多 1 次真实 HTTP attempt；重试=0；不调用 VLM；不渲染、不重新处理比赛。**
- 使用**本次 fresh E2E 的** 05_v3a/round_01/planner_context.json，而非历史 P1 EDL 或 Planner 缓存。
- 在当前 Python 进程内设 STORY_PLANNER_THINKING_OBJECT_DISABLED=1，删除与其冲突的 flat thinking 配置；发送 thinking: {type:disabled}。
- 保留原 timeout（通常 60 秒）作为单变量诊断；**不要同时调高 token 和 timeout**。
- 输出 token 上限 2048；预估 API 费用上限 USD 0.03（估算值，不是账单硬上限）。
- 真实调用失败时保留失败状态，不自动重试或降级后冒充成功。

结果在新目录：

- planner_smoke.json：模型返回是否真实、是否有效 JSON、有效 video_tool_requests 数量、错误类别、token、费用估算及脱敏片段。
- diagnostic_summary.json：PLANNER_READY_FOR_VLM 或 PLANNER_NOT_READY；real_http_executed 与调用统计。

**通过标准**：同一次真实 Planner 响应解析和校验通过，且至少 1 个 video tool request 合法绑定到 fresh trusted anchor。PLANNER_READY_FOR_VLM 只表示 Planner 可进入下一步，**不表示 VLM 已调用或多模态闭环完成**。

### 3. 立即停止并汇报

不运行 run_v3a_fresh_A_real.sh，不再执行第二次 Planner 请求，不开展 VLM 或全场 3 轮实验。

汇报：测试结果、配置预检、溯源哈希与 EDL 差异、Planner 成功/失败、工具请求数量、请求 audit thinking 标志、token、实际 HTTP attempts 和预估费用。若失败，根据具体证据建议下一步是超时调整、token/响应解析还是 prompt/schema 修复；**只建议，不自动付费继续**。

注意：脚本和单元测试是在 GitHub 提交，尚未在服务器运行；不得在没有实际执行证据时标记为 PASS。
