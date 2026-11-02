# 咪咕故事链 V2 — G2.3 首次直播定向核验与候选证据纠偏

> Cursor 执行。工作分支 `story-va-video-driven`。本任务依据 G2.2 @ `a0d112691dec57ab4b5bfa6a4f593967db14817c` 和 `STORY_VA_V2_G2_2_FIRST_LIVE_RETRIEVAL_REPORT.md`；仅做零付费本地片段核验、必要的防误判小修、人工审片交接；**不调用付费 VLM/API，不生成正式长集锦，不改 G1 主线，不使用 V1 / causal / gold / 跨场缓存**。所有 `render_ready=false`、`n_video_verified=0`，除非此后经过可审计真实视频语义核验，且不得冒充智能体自动核验。

## 一、现有 G2.2 应保留的成果

- A 左方：0:1→1:1→2:1；B 右方塞尔塔末段：2:1→2:2→2:3；六角色新 Top-1 均已脱离失败 `late_third`；没有已证实首播进球。
- A strongest lead 为 `event_000661` LIVE Shot @ **6774.49**，候选窗口 **6767.67–6778.15**；G2.2 的 `net_sec≈6778.49` 是 `shot+4s` **纯推测**，而且大于候选窗口终点 6778.15。即便视频不包含入网，仍不得标成完整首播进球。
- 上述确认时间与视频动作有明显时间差。不能将比分确认 @6957.12 直接当入网时间，也不能把普通 LIVE Shot 视为 2:1 进球。

## 二、优先核验 A go_ahead，而非再大规模搜索

1. 从本场 G2.2 `candidate_evidence_index.json` / `role_first_live_pack.json` 找回 `event_000661` 候选源片。用 `ffprobe` + 真实源 PTS 确认 `6767.67–6778.15` 与帧索引。**先真实看片**：球权/队伍、射门前推进、球轨迹、守门员反应、是否入网、是否出现回放切换。
2. 根据原始事件 REPLAY 起点（报告约 6781s，但必须重新核实）和原始媒体连续性，可以额外导出包含后续 2–5 秒的 **审片扩展版本**；原版不得覆盖。严禁越过回放转场后仍将其标为同一首次直播镜头；如果完整入网镜头无法保留，明确 `SHOT_ONLY_NET_UNRESOLVED`。
3. 同时抽查 Top-K `event_000655` @6703s 和其他候选。若 `event_000661` 是被扑救、射偏、回放或不属于阿联酋反超，退回 unresolved 并记录证据；不得以离 score confirmation 最近为由直接选它。
4. 提供带来源 PTS、相对秒、关键截图、实际 SHA256 的一条 `A_go_ahead_000661_review.mp4`、一条 `A_go_ahead_000661_extended_review.mp4`（如果安全延长可行）和 `A_go_ahead_alternative_000655_review.mp4`（存在时）。审片短片是连续源片裁切，不是回放/直播拼接。

## 三、修复检索层的“虚构 net”表达问题

- 在 `v2_g2_first_live_retrieval.py`，将 `shot_sec+4.0` 生成的 `hyp_net` 明确标为 `hypothesized_result_sec` 或 `search_end_hint_sec`。不能放入让下游误以为真实 `net_sec` 的已验证事实字段；只用作搜索/排序边界。
- 若候选 `media_out` 小于假设结果时间或不含真实入网观测，候选必须 `SHOT_ONLY/NET_UNRESOLVED`，不能标 `claims_continuous_live=true`；基于事件 `broadcast_phase=LIVE` 也不是视频连续直播的独立视觉核验。
- 在送入通用 EDL 前继续使用 `v2_video_evidence_gate` 的实际身份、PTS、帧、语义审计门禁；不得仅根据 `status=verified` 或事件 `LIVE` 自动升级。
- 新增可复现单测：假设入网晚于片段终点、仅有 LIVE Shot 无入网、已进入 replay 才见 net、网内球出现在另一机位、错队伍、普通射门但比分稍后变化，都不能升级 `verified_first_live`。旧 G2.1 B post-score replay 是负控制，不得回归。

## 四、导出新版 6 条主候选，交给实际审片

从 `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/g22_first_live/{A_uae_oman,B_osasuna_celta}/` 读取各角色真实 `role_first_live_pack.json`，定位最新 Top-1 原始短片。**不得直接用文件名或报告说文件存在**，逐一检查实际路径/大小/可播放性/SHA 和来源 PTS。

在新独立目录（例如 `.../cross_match_g2/g23_targeted_review/`）生成六条易上传的 720p H.264 审片 MP4 + `six_g22_top1_review.zip`，另加 A go_ahead 重点扩展版及第二候选。manifest 中明确每条是：
- `candidate_only`，`NOT_VERIFIED`；
- `source_pts_start/end`、原视频/衍生片身份及 SHA、连续源片剪辑的定义；
- `observed_shot` / `observed_net` / `first_live` 三项全部先为 `review_pending`，严禁预填 PASS；
- B 三条旧 `late_third` 和 A 庆祝片为此前已拒负例，不可当新的正例。

## 五、G2.3 STOP/GO 与汇报

- **首先判断 A 000661**：只有审片实证支持同一次连续首播 shot→net、正确阿联酋且比分逻辑一致，才将其标为 `human_visual_review_supported_candidate`。即便人工通过，`agent_auto_verified=0`，不得宣称自动视觉核证成功。
- 如果 A 000661 无 net 或是普通射门，优先检查 000655 / A 同场其他 Top-K，随后报告检索是否需要视觉模型；不继续无界“往前挪几个窗口”。
- B 仅做新版 3 条主候选的视频打包、视觉审片交接；除非有真实视频语义证据，不升级 verified。
- 最终交付：`STORY_VA_V2_G2_3_TARGETED_REVIEW_REPORT.md`（含 A 000661 初审、Top-K、六个 Top-1 源 PTS、打包路径、修复详情、反例测试结果），文本报告正常 commit/push；大型 MP4 只留服务器。API=0，正式成片=0。
- 不重做 G1，不改 V1、8.31 或 Croatia R2.9。完成时报告 HEAD、测试、六条 MP4 和重点 A 视频绝对路径、`n_video_verified` 真实值、是否需要用户上传 ZIP。
