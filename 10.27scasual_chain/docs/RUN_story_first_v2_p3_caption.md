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
