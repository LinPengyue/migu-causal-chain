# G2.1 — A/B 翻盘故事链六段主候选人工审片交接（Cursor 指令）

> 本任务承接 G2 @ `5ac591fb8269e85484b8a546fc1f1a6640ebecd0`。只制作**可上传、可人工逐帧复核**的视频证据包，不再次跑模型、不修改规则、不渲染正式故事成片。工作分支 `story-va-video-driven`，先 pull、记录真实 HEAD。保持 `render_ready=false`。

## 一、起点与准确理解

G2 报告已记录：
- A 阿联酋–阿曼：`G2_A_EVIDENCE_PACK_READY`；opening_deficit/equalizer/go_ahead 每个角色 7 个候选，共 21 条；全部 `NOT_VERIFIED`。
- B 奥萨苏纳–塞尔塔：同样 21 条、全部 `NOT_VERIFIED`；主角 right / 塞尔塔，**选中末弧** `2:1→2:2→2:3`。
- 40s 左右的 `late_third` 连续片段，是基于比分确认前后的候选检索窗，**不是自动确认的进球片段**。比分时刻不是起脚或入网时刻。

禁止调用付费 API；不许用 V1 时间、`*_causal.json`、gold 或克罗地亚缓存为 A/B 判定进球。既有 G1/G2 输出只读。

## 二、先整理六段主候选视频

从实际 G2 产物目录读取（不可凭仓库文档推断文件已存在），每场各三个主候选：

A 基础目录：`/data2/lpy1/_story_va_outputs/v2/cross_match_g2/A_uae_oman/`

- `roles/opening_deficit/clips/opening_deficit_late_third_clip_source_continuous.mp4`
- `roles/equalizer/clips/equalizer_late_third_clip_source_continuous.mp4`
- `roles/go_ahead/clips/go_ahead_late_third_clip_source_continuous.mp4`

B 基础目录：`/data2/lpy1/_story_va_outputs/v2/cross_match_g2/B_osasuna_celta/`

- 同三条路径，其中角色名相同；B 的 opening_deficit 针对 **2:1**，不是最早 0:1。

逐文件 `test -f`、`ffprobe`、sha256；若文件不存在如实报告 `MISSING_FILE`，不得偷偷改用另一候选却仍叫同名。读取 G2 `candidate_evidence_index.json`，把每条剪辑和来源 MP4 的原始 PTS、输入哈希、role 绑定。

## 三、产出能传给人看的文件

新建 `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/human_review_handoff/`：

1. 六条**单独可播放**压缩审片 MP4（建议 720p H.264，保证比分牌可读、画面动作可见，保留音频）。文件名含比赛、role。审片压缩版本的时间轴与原视频连续一一对应；不允许跳过/重排/补帧/把多个回放拼成“直播”。保留原始 G2 clips 不改。
2. `review_manifest.json`：每条包括 `match_id`、role、源视频/原剪辑 SHA、start/end source PTS、clip duration、fps、审片版 SHA、原始截图索引、视频来源和说明。全部显示为 `candidate_only`。
3. `REVIEW_CHECKLIST.md`：给每条审片留空的观察栏：是否出现射门、是否出现入网、进球队伍归属、是否是首次直播/疑似回放、比分牌是确认而不是动作、关键镜头是否完整、是否需要查本角色其他 6 条候选。**所有栏先写 待审，不填写猜测**。
4. 一个 `six_clips_review_index.md`，列 6 条视频的绝对路径、大小、建议观看顺序以及哪个需要优先上传。**优先把六个单文件或打包 zip 上传到当前 ChatGPT 会话**（Cursor 如不能直接上传则把路径给用户，不冒充已经上传）。
5. 如需合成六段串联便于看，可以额外生成 `review_compilation.mp4`，每段开头清楚标明比赛/role/源 PTS；拼接片**仅是审片导航**，不能作为源直播连续性证明，单文件仍是核验依据。

不要将大型 MP4/JPG 推送 GitHub。文本 manifest 和索引可选只推摘要至 `10.27scasual_chain/docs/STORY_VA_V2_G2_1_HANDOFF_REPORT.md`。

## 四、关键验收与下一步分流

- 用户/ChatGPT **实际观看**后，逐角色输出 `SHOT_NET_LIVE_SUPPORTED`、`REPLAY`、`SCOREBOARD_ONLY`、`WRONG_TEAM`、`NO_GOAL_IN_WINDOW`、`UNCERTAIN`，并给实证 PTS。
- 如果主候选不是进球，应回查该角色其余 6 条候选和更大搜索窗，不能为追求 PASS 强制提取 shot/net 或通过人工旧时间定点。
- 即使人工观看确认了进球，也要记录 `verification_method=human_visual_review`，不能计成“智能体自主视频语义核验成功”。
- B 的 `opening_deficit` 检查报告曾提到 `score_before=[0,0]` 可能是搜索底账；本轮核查对应的 selected arc、2:1 事实以及导出窗口，不得据错误元数据升级已验证。
- 没有实际独立视频核验前，两场依然 `n_video_verified_goals=0`、`render_ready=false`；不启动正式故事长视频，也不作交付 PASS。

完成后正常 commit/push**文本报告或必要脚本**，不改 V1、8.31、Croatia R2.9；汇报 6 个实际可播放文件绝对路径、大小、源 PTS、SHA、测试、API=0、Git SHA，并说明用户需要上传哪些文件供审片。
