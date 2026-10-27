# Story Video Agent Phase 2A — 本地视频工具

## 范围
- FFprobe / FFmpeg 接入；`dry-run` 与显式 `media-only`
- 粗搜索 `coarse_search_interval`（≤90s）与局部 `inspect_story_window`（≤16s）分工具
- seed 优先、分层 interval、全局帧预算与缓存；抽帧只标 `sampled`
- `_comeback_score_steps` 对齐 T01 最后一次逆转弧

## 测试
`PYTHONPATH=. python3 -m unittest story_video_agent.test_dry_run story_video_agent.test_media -v` → 15 OK

## 克罗地亚 media-only（本地 `/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4`）
- status: `frame_budget_exhausted`（预算 8）
- frames: 8；elapsed ≈ 6.06s；`verification_complete=false`
- setup/buildup 各采一层后停，未扫完全部 search_intervals
- 详见 `story_video_agent_phase2a_manifest.json` / `story_video_agent_phase2a_croatia_summary.json`
- 帧 JPG 不入库（gitignore）
