# V3-A Fresh E2E：阿联酋 vs 阿曼集成验收（2026-11-05）

## 目标与边界

本工作只拼接现有算法，不开发新算法。入口为 algo/story_video_agent_v3/fresh_e2e_cli.py；测试为 tests/test_v3a_fresh_e2e.py。基于 P0 修复 ca607e9 创建独立分支，不修改冻结 V3-R / V3-A / P0。

**默认零付费**：Agent 离线 degraded 编排不能冒充 DeepSeek/Qwen 真实成功。本文件不宣称已经在远程服务器上运行过完整比赛。

## 阿曼 A 场历史中间产物溯源

历史根目录（只读）：/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman

| 产物 | 生成算法 | 新运行是否复用 |
| --- | --- | --- |
| 01_enrich/events_enriched.json | atomic_event_enrich.enrich_files | 否，仅比较 |
| 02_strip831/strip_A_original.json | v2_strip_reinfer.run_strip_predict / AlgoStripAdapter | 否，仅比较 |
| 03_v1_adapt/predicted_causal.json | v1_causal_adapter.strip_chains_to_v1_causal | 否，仅比较 |
| 03_v1_adapt/predicted_causal_live_goals_only.json | closed_loop_cli replay filter | 否，仅比较 |
| 04_phase5/t01_story.json | story_chain.end_to_end.run_paths | 否，仅比较 |
| 04_phase5/story_plan.json | narrative_composer.compose_story_plan(use_llm=False) | 否，仅比较 |
| 04_phase5/candidate_edl.json | phase5_pipeline.run_phase5 | 否，仅比较 |
| 04_phase5_p1_polish/candidate_edl.json | 后续 P1 质量收尾 | **只作质量对照** |
| v3a_cross_match_3round_20261104/ | 旧 V3-A 三轮 | 否，仅作为退化样例 |

历史 raw EDL SHA256 bba0ec4d…，成片约 106.9 秒；P1 polish EDL SHA256 f259da7b…，成片约 94.9 秒。重新运行现有算法首先应对照 raw，而非声称自动重现后期 P1 polish。

原始输入（需在服务器检查文件确实存在）：

- 事件：10.27scasual_chain/data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json
- 原子补全来源：同目录的 10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语_causal.json
- 视频：/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4

人工 causal JSON **仅**进入原子补全；8.31、T01、Composer 和 V3-A 不接收人工因果链关系。现有 atomic_event_enrich 仍会从人工链的 is_replay 推断原子回放标志，这不是独立视觉核验，需在报告中标明。

## 服务器运行（零付费）

先检出本分支到独立 worktree，进入仓库根目录，然后执行：

~~~bash
export PYTHONPATH="$PWD/10.27scasual_chain/algo"
ROOT="/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman"
MATCH="10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语"
VIDEO="/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4"
EVENTS="$PWD/10.27scasual_chain/data/交付_out/$MATCH.json"
CAUSAL="$PWD/10.27scasual_chain/data/交付_out/${MATCH}_causal.json"

test -f "$VIDEO" && test -f "$EVENTS" && test -f "$CAUSAL" || exit 1
python -m unittest discover -s 10.27scasual_chain/tests -p test_v3a_fresh_e2e.py -v

python -m story_video_agent_v3.fresh_e2e_cli \
  --match-id "$MATCH" \
  --events "$EVENTS" \
  --causal-atoms "$CAUSAL" \
  --video "$VIDEO" \
  --algo-root "$PWD/10.27scasual_chain" \
  --history-root "$ROOT" \
  --out-dir "$ROOT/fresh_e2e_A_20261105_offline"
~~~

输出目录必须为空/不存在。历史目录只用于读取来源报告和进行事后 SHA 对照，不作为算法输入。不能使用 gold、旧预测、旧 EDL、旧 Stage-2 proposal 或旧模型缓存。

## 新产物

~~~text
fresh_e2e_A_20261105_offline/
  00_input_manifest.json          # 原始输入 SHA256、历史溯源、算法链
  01_to_04_fresh_v3r/
    01_enrich/events_enriched.json
    02_strip831/strip_A_original.json
    03_v1_adapt/predicted_causal.json
    03_v1_adapt/predicted_causal_live_goals_only.json
    04_phase5/t01_story.json
    04_phase5/story_plan.json
    04_phase5/candidate_edl.json
    04_phase5/story_clean.mp4      # 新生成的 V3-R raw 基线
  05_v3a/
    baseline_resolution.json
    self_revise_summary.json
    best_candidate_edl.json
  06_candidate_render/
    candidate_edl.json
    story_clean.mp4                # 新生成的候选视频
    story_qc.mp4
  fresh_e2e_summary.json          # 逐阶段 SHA 对照及执行结论
~~~

## 验收与未完成事项

1. 对照每阶段的新旧文件 SHA256；若不一致，核查源输入、代码提交、参数和算法随机性，不要通过硬编码追平。
2. V3-A 强制 prefer_p1_polish=False，直接消费本次新生成的 Phase5；stage2_proposal=None，audit_path=None。
3. Agent 没有接受修订时，最佳 EDL 必须与本次 V3-R 初稿一致。
4. 渲染前过滤 include_in_cut=False，拒绝明确回放、SUSPECTED_REPLAY 和重复进球片段。
5. 即使成功输出 MP4，仍是 candidate_only，render_ready=false，不等于首次 LIVE 视觉验收。
6. 真实 API 三轮需要另外批准，使用 --enable-real-api --i-approve-budget 双门禁，并设置费用/调用上限。当前没有批准或运行。

**已验证**：5 个 mock/stub 编排测试在隔离 Python 环境通过，覆盖输入输出接线、历史只读、双预算授权、回放拒绝和非空目录保护。

**尚未验证**：仓库完整测试、服务器上真实 A 场全链路、视频渲染结果、真实 DeepSeek/Qwen 增益。
## 2026-11-05：用户批准阿曼 A 场真实 API 端到端一次

本分支新增 `scripts/run_v3a_fresh_A_real.sh`，只针对 A 场封装通用集成入口。用户批准了**一次**真实 API 试验，不等于批准自动续跑或跨场付费。

服务器独立 worktree 中先安全加载原有 DeepSeek / Qwen 端点环境变量（`STORY_LLM_BASE_URL`、`STORY_LLM_API_KEY`、`STORY_LLM_MODEL`、`STORY_VLM_MODEL`，必要时 `STORY_VLM_BASE_URL`、`STORY_VLM_API_KEY`）；**不要把密钥粘贴进聊天、命令行参数或 Git**。执行：

~~~bash
bash 10.27scasual_chain/scripts/run_v3a_fresh_A_real.sh
~~~

本脚本会先执行单元测试，然后用 `--enable-real-api --i-approve-budget` 执行 3 轮（不因实验质量阈值提前停止），最多 24 次 HTTP 尝试，预估成本上限 USD 0.30、每次输出最多 2048 tokens。**预估费用不是账单硬上限**。输出目录自动以时间戳命名，不能覆盖历史结果。

真实 API 端点配置预检发生在重新处理视频之前；无密钥则失败，不能静默当成 mock 成功。新增 `api_preflight.json`（不含密钥）、`fresh_e2e_summary.json.agent.real_planner/real_vision/real_verifier`、`real_multimodal_round_trip` 与 `render_selection`。

- `completed_real_multimodal_candidate_only`：至少有真实 Planner、Vision、Verifier 参与（不代表视频质量提升）。
- `completed_degraded_candidate_only`：未完成全部三类真实模型参与；不得宣称真实 Agent 成功。
- `baseline_safety_fallback`：Agent 修订未通过回放/重复剪辑检查，视频回退到**本次** V3-R 初稿；不丢弃被拒 EDL 的审计证据。
- `failed`：查看 `fresh_e2e_summary.json.error`，禁止将部分结果当成功。

验收需要实际读取 `05_v3a/self_revise_summary.json` 每轮 Planner/VLM/Verifier、`api_usage.real_ok/real_failures/est_cost_usd_real`，以及新旧 EDL diff；再看片比较 V3-R raw、V3-A candidate、历史 P1 polish，重点检查 opening 是否重复、三个进球是否首次 LIVE、是否有比分滞后误锚和镜头节奏退化。

**本聊天只完成了 GitHub 代码/运行脚本提交，没有服务器 shell / 私有 MP4 / API 密钥访问，因此没有执行真实 API 或渲染。**
