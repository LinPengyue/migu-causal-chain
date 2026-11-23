# 212 条候选故事链：原子事件 / 短程因果链证据预标注（非金标）

- 范围：98 场比赛中原有的 212 个「比赛 × 故事类别」候选，覆盖其中 94 场；另有 4 场无候选类别。
- 数据格式：每条故事的 `segments` 依叙事顺序排列，每段仅有一种 `source_type`：`source_event`（引用事件 `event_id`）或 `source_chain`（引用短程因果链 `annotation_id`）。
- `start_sec` / `end_sec`：仅来自原子事件的 `media_time.start_time_sec/end_time_sec`，或短程因果链的 `segment_time_video`；绝不由事件时间点、`t_ms`、`segment_time_sketch` 推造。
- `source_archive` + `source_json_path` + 源 ID 共同标识唯一源记录；两套标注的 ID 不互通。各原视频独立时间轴。
- 限定来源：已标注为 LIVE 的原子事件、非回放且含至少 2 节点的短程因果链；**元数据 LIVE 不是 FIRST_LIVE 视频证明**。
- 文件：`part_*.jsonl` 为 212 条候选预标注（每行一条）；`reference_qa.json` 是源 ID、时间区间和非回放条件的自动核对。
- 尚未完成：逐场确认球员/球队身份、比分有效性、战术发展、节点之间的叙事关系、独立故事成立性及实际首次直播镜头。这些未完成项不得伪装成金标或正式 EDL。
- 关键回合候选可能标记为 `NODE_ONLY`，证据空缺为 `NO_SOURCE_SEGMENTS`；不能强制凑成一条完整的长程故事。
- 不修改既有的 `11.20sstory_chain` 产品实现。

本目录为机器辅助的、源文件可追溯的初稿。正式 benchmark 金标必须经人工审核与视频复核。
