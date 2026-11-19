# Story-First V2 P3 实片接续

在 `10.27scasual_chain` 下运行。复用已渲染的 H5 和 P2 的窗口核验记录。源素材、已交付 EDL 和两个输入 MP4 以只读方式使用。

```bash
p3_trial=/tmp/lpy1_story_first_v2_p3_isolated_trial_20261116
p3_events=/tmp/lpy1_v3a_p14_cv_integration_20261113/run/01_to_04_fresh_v3r/01_enrich/events_enriched.json
p3_source='/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4'
p3_args=(
  --trial-artifacts docs/artifacts_story_first_v2_p3_isolated_trial_20261116
  --source-review docs/artifacts_story_first_v2_p3_ready_offline_20261116/review_gate_result.json
  --pool docs/artifacts_story_first_v2_paid_round1_20261116/story_first/story_first_pool.json
  --baseline-mp4 "$p3_trial/baseline/story_clean_original.mp4"
  --trial-mp4 "$p3_trial/trial/story_clean_trial_h5.mp4"
  --history docs/artifacts_story_first_v2_p3_eval_offline_20261116/critic/dual_structural_compare.json
  --max-rounds 2
)
p3_run_name=$(date +%Y%m%d_%H%M%S)
PYTHONPATH=algo python -m story_video_agent_v3.story_first_p3_cli "${p3_args[@]}" \
  --out-dir "/tmp/story_first_p3_preflight_$p3_run_name"
```

离线结果应为 `PREPARED_OFFLINE`、0 HTTP。实片调用通过 Caption 和 Planner 各一次启动。只有 Planner 选择合法的缩短或替换动作才重渲并进入下一轮。替换涉及新素材时会调用现有 P2 源核验。以下配置给两轮预留最多 5 个 HTTP 尝试，自动重试为 0，费用上限按现有 Provider 的已发生费用估算执行。

```bash
STORY_API_ENABLE=1 PYTHONPATH=algo python -m story_video_agent_v3.story_first_p3_cli "${p3_args[@]}" \
  --source-mp4 "$p3_source" --events-json "$p3_events" \
  --enable-real-api --i-approve-budget --max-calls 5 --max-cost-usd 0.05 \
  --out-dir "/tmp/story_first_p3_caption_$p3_run_name"
```

检查 `p3_revision.json` 中的停止原因、选中的预览及使用量。每轮目录有 `caption_input.json`、`caption.json`、`planner_input.json`、模型调用记录及动作转移。触发重渲时，`edit_*` 目录包含生成的意图、临时 EDL 和视频。报告记录实际收到的动作和证据。KEEP 指选中的预览版本供审片，正式交付状态由现有 EDL 门禁管理。

## H5 接续第二次修订

在上面的 `p3_args` 基础上追加下面两个参数。服务器若移动了预览，使用 SHA-256 相同的文件。0 次取 H5 初始试剪，1 次取用户已审片的 6.26 秒桥段版，V3-R 原版保留为额外参考。只有新动作实际渲染且通过时间线校验，才记作第 2 次修改。若模型保留现版，比较报告里只有 0 次和 1 次成片。

```bash
p3_args+=(
  --resume-trim-artifacts docs/artifacts_story_first_v2_p3_caption_20261119
  --resume-mp4 /tmp/story_first_p3_caption_20261119_123121/round_01/edit_01/rerender/story_clean.mp4
)
PYTHONPATH=algo python -m story_video_agent_v3.story_first_p3_cli "${p3_args[@]}" \
  --out-dir "/tmp/story_first_p3_loop2_preflight_$p3_run_name"

STORY_API_ENABLE=1 PYTHONPATH=algo python -m story_video_agent_v3.story_first_p3_cli "${p3_args[@]}" \
  --source-mp4 "$p3_source" --events-json "$p3_events" \
  --enable-real-api --i-approve-budget --max-calls 5 --max-cost-usd 0.05 \
  --out-dir "/tmp/story_first_p3_loop2_$p3_run_name"
```

比较清单在 `p3_revision.json` 的 `edit_count_comparison`。Caption 审计按前接点、桥段本身和后接点记录描述是否存在，后接点最多覆盖 15 秒且限制在相邻片段内。接续运行复用第 1 次修订的成片，无需重新生成候选或重渲第 1 次修订。

## 新版 P3 与 P3.5 外层对照

先在 Cursor 服务器上运行专项回归。三次有效 TRIM、缺少 Caption 时保留试剪、第二轮新增成功以及回放标注阻断都由测试覆盖。

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_story_first_p3.py tests/test_v3a_story_first_closed_loop.py
```

复用本页前两段中的 `p3_args` 定义，其中包含已选 H5 的 checkpoint 和 MP4。命令会核对三份输入视频与归档记录。先以零 HTTP 复核 V3-R 与第一轮，随后在相同输入上只运行第二轮。沿用原 P1 Flash、Revision Planner 和 Vision 配置。

```bash
p3_run_name=$(date +%Y%m%d_%H%M%S)
PYTHONPATH=algo python -m story_video_agent_v3.story_first_p3_cli "${p3_args[@]}" \
  --outer-rounds 1 --out-dir "/tmp/story_first_h5_checkpoint_$p3_run_name"

STORY_API_ENABLE=1 PYTHONPATH=algo python -m story_video_agent_v3.story_first_p3_cli "${p3_args[@]}" \
  --source-mp4 "$p3_source" --events-json "$p3_events" \
  --outer-rounds 2 --enable-real-api --i-approve-budget --max-calls 12 --max-cost-usd 0.05 \
  --out-dir "/tmp/story_first_outer_h5_$p3_run_name"
```

以 `outer/story_first_outer_comparison.json` 的三行分别对应 V3-R、第一轮和第二轮。提交对照时提供每行时长、视频路径和 SHA-256、第二轮 P1 候选数、实际新增窗口、P2 否决原因或 P3 局部调整记录。第二轮若没有可用新素材，就记录停止原因和沿用的第一轮 SHA-256。只有执行重渲且通过对齐的局部 TRIM 计入 `local_trims`。一次外层尝试计入 `attempted_outer_rounds`，实际新增计入 `accepted_changes`。三列都是预览比较，正式交付入口继续使用原有门禁。

从 V3-R 新开端到端运行时，`story_e2e_cli --enable-story-first --story-first-outer-rounds 2` 会在首轮 P3 接受后运行 P3.5，并在 `story_first_outer/` 产出同结构的对照。

## B 场从首次回放拒绝续跑

从本目录执行，沿用已有的模型环境。P1 复用首次运行的两个区间，经原片、EDL 和提案校验后读入其 P2 回放拒绝。更新后的 H1 与其余候选一并交给 Planner，随后重新走 P2 Verifier。

```bash
b_root=/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_B_osasuna_celta
b_prior=/tmp/story_first_outer_osasuna_celta_20261119_161929
b_out="/tmp/story_first_outer_osasuna_celta_replay_$(date +%Y%m%d_%H%M%S)"
STORY_API_ENABLE=1 PYTHONPATH=algo python -m story_video_agent_v3.story_e2e_cli \
  --match-json 'data/交付_out/10月27日_25-26赛季西甲第10轮_奥萨苏纳VS塞尔塔_国语.json' \
  --events-json "$b_root/01_enrich/events_enriched.json" \
  --source-mp4 '/mnt/data4/migu/10月27日 25-26赛季西甲第10轮 奥萨苏纳VS塞尔塔 国语.mp4' \
  --phase5-dir "$b_root/04_phase5_p1_polish" --out-dir "$b_out" \
  --story-first-artifacts-dir "$b_prior/story_first" \
  --enable-story-first --story-first-outer-rounds 2 --max-rounds 2 --phase8-paid-multi-round \
  --enable-real-api --i-approve-budget --max-calls 16 --max-cost-usd 0.05 --no-smoke-render
```

核对 `story_first/story_first_pool.json` 的 `replay_revision_history` 里有 H1 替换记录。Planner 输入在 `02_round_01/paid_api/story_first_replay_replan/planner_input.json`，首次运行产生新回放拒绝时也可检查 `02_round_02`。回传 Planner 的选择、P2 结果，以及有产出时的 `story_first_outer/story_first_outer_comparison.json`。
