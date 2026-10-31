# 咪咕足球故事链 — V1 / V2 3:1 原始画面对照任务（仅核验，不改算法）

> **给 Cursor Agent**：先完成可供用户实际观看的 V1/V2 视频对照，再判断 V1 跳过源片损坏的剪辑是否可借鉴。**本任务不授权修改 V2 选片算法、进球识别、故事规划或交付门禁；不得直接把 V1 裁剪时间回灌 V2。**

仓库：`LinPengyue/migu-causal-chain`  
工作分支：`story-va-video-driven`；执行前正常 pull，勿改 `main` / force push  
V1 冻结标签：`story-va-v1.0-structured-baseline`（SHA `462ea11b8af55429def3c4dd3739e7fa9d6c9153`）  
V2 最新候选：R2.9，服务器目录 `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_9_targeted_qc/`  
原始 MP4：`/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4`

## 一、此任务的唯一要回答的问题

**V1 对 3:1 直播进球跳过原始视频约 0.9 秒（6315.800–6316.700s）后，真实画面是否仍保留完整、自然、连续可理解的关键射门与入网过程？** 如果跳过导致射门/球路突变、动作缺失或明显跳切，V1 即使没有花屏，也不代表它比 V2 更符合当前严格交付条件。

不能用“V1 观感好”“V1 有 glitch_avoidance”“有 story_clean.mp4 文件”代替实际看片结论。

## 二、已从 V1 冻结仓库核实的依据

1. `10.27scasual_chain/reports/phase5/match_profiles/croatia_glitch.json` 明确记录 `third_goal_approach_neon_band`，源片区间 **6315.8–6316.7s**。
2. V1 `10.27scasual_chain/reports/phase5/croatia/phase5_manifest.json` 的历史渲染 EDL：
   - `seg_lead_extend_1_goal_action_approach`: **6305.199–6315.800s**
   - `seg_lead_extend_1_goal_action`: **6316.700–6327.199s**
   - `seg_lead_extend_1_scoreboard`: **6407.700–6411.200s**
3. V1 对 2:1 的历史候选区间是 **3511.574–3533.574s**，可能仍包含当前 V2 发现的约 3520.15s 源宏块；不要笼统称 V1 全片干净。
4. 冻结仓库历史 manifest 记录 V1 全片候选 `story_clean.mp4` 时长约 **131.44s**，路径：`/tmp/migu-va2c/10.27scasual_chain/_local_render/phase5/croatia/story_clean.mp4`。这只是**历史生成时的路径**，必须检查服务器是否仍存在；不可声称当前已找到。
5. V1 使用人工 `*_causal.json`，仅允许作为**隔离的离线视觉对照**。严禁向 V2 Planner、Agent、事件增强、搜索窗口、缓存、训练或调参注入 V1 的人工因果链、候选时间或故事角色。

## 三、执行步骤（按顺序）

### 1. 查找 V1 历史成片，不要假定路径仍有效

- 检查上述 V1 `story_clean.mp4`、`story_qc.mp4` 及 V1 worktree 历史目录（可能包括 `/data2/lpy1/worktrees/migu-story-va-v1`）是否真实存在，使用 `ffprobe` 验证可播放、时长和媒体信息。
- 若找到，**只复制**到独立审查目录，保留原文件 SHA256、来源路径，禁止覆盖 V1 历史文件。
- 若未找到，不要把“未找到产物”理解成“V1 不存在”；使用冻结 tag 的 `candidate_edl.json` / manifest 和**同一原始 MP4**，只重建必要的**3:1 对照片段**。生成文件须标记 `V1_EDL_reconstruction`，绝不能声称是找回的“历史 V1 原始成片”。
- 不因重建对照而运行 V1 推理、修改其冻结代码、读取 V1 结果进入 V2 运行时。

### 2. 生成用户直接可看的对照视频（必须实际产出 MP4）

建议新建 `/data2/lpy1/_story_va_outputs/v1_v2_3_1_visual_comparison_20261031/`。最少交付：

1. `source_3_1_continuous.mp4`：从原始 MP4 **6305.199–6327.199s** 准确裁切的**连续首次直播候选**，不能偷跳坏帧，保留源 6315.8–6316.7 色带供对照。
2. `v1_3_1_glitch_avoidance.mp4`：优先从真实 V1 历史成片提取对应两段；若历史 MP4 不存在，则根据冻结 EDL 将 **6305.199–6315.800** 与 **6316.700–6327.199** 准确解码、裁切并拼接。记录 `from_original_v1_final` 或 `V1_EDL_reconstruction`，后者不得冒称历史实际渲染质量相同。
3. `v2_r29_3_1_current.mp4`：从 R2.9 **实际 Clean MP4** 提取 g31 段（依据 R2.9 实际 EDL 的渲染时间映射，不直接用上一版时间）；不能误用 QC 叠字版作为 Clean。
4. `compare_v1_v2_3_1.mp4`：制作容易观看的对比版，标明每路来源、原始源 PTS、`V1 skipped 6315.8–6316.7`。若同步并排，**不能通过隐藏地拉伸/冻结 V1 的 0.9s 来伪造时间连续性**；需要在跳过区间明确标示 `V1: skipped 0.9s`，必要时改用顺序播放并在转场注明。
5. 若历史 V1 全片仍在，另复制 `v1_story_clean_historical.mp4` 供用户完整观看；若无法取回，则不强行重建整个故事成片，优先 3:1 对照。

所有输出实际 `ffprobe` 校验、可播放、不只是 JSON 帧图。控制体积，生成便于上传给 ChatGPT / 用户的可观看短片，**不要把大型 MP4 推送进 Git 仓库**。

### 3. 人工可复核的 3:1 动作与接缝审计

- 分别检查 `6313.5–6318.0s`（射门及损坏附近）与 `6318.0–6322.5s`（入网结果），保存原分辨率关键帧、接缝前后连续 1s、短片，指出球的轨迹、球员动作是否出现空间跳跃/不连续。
- 逐项明确：
  - V1 是否完全没有明显彩色条带？
  - V1 跳过 0.9s 后，**起脚/球路/入网是否仍真实可见、可理解**？
  - V1 在 6315.8→6316.7 的拼接是否产生不自然硬跳？
  - V2 R2.9 是否保持了完整的首次直播动作，但存在源花屏？
  - 如果 V1/重建 V1 只保留门前结果而缺起脚/球路，必须标记 `ACTION_INCOMPLETE`，不可宣称修复成功。
- 同时对 V1 2:1 候选 **3511.574–3533.574s** 抽取 `3520.0–3520.5s` 作为**次要抽查**，判断其是否仍包含源局部破损，避免将 V1 简化为“全部无花屏”。
- 仅凭源片/EDL 推算出裁切区间，不等于看过实际成片；报告必须准确区分“实际渲染 MP4 观测”与“EDL 推断”。

### 4. 仅给比较结论与下一步建议，本任务不要直接改 V2

给出以下三选一的**证据驱动**结论：

- `V1_SKIP_ACCEPTABLE_CANDIDATE`：V1 裁切接缝肉眼自然、进球关键动作确实完整；则**提出** V2 可考虑建立基于原始源自主 QC 的坏段跳过机制，**但先提供对照片段让用户确认，不立即修改或交付**。
- `V1_SKIP_BREAKS_GOAL`：V1 虽然隐藏花屏，但导致关键动作缺失或突兀跳切；V2 继续标源损坏硬阻塞，建议取得干净首次直播来源。
- `INCONCLUSIVE`：证据/历史成片缺失，无法充分判断；列出确切缺口，不允许填补猜测。

**绝不把 V1 历史 EDL 的 6315.8/6316.7 直接当作 V2 模型预测或运行时输入。** 此轮可以为**隔离离线审计**查看 V1 时间区间；V2 只能从自身视频质量检测和源媒体信息独立发现可跳过范围，之后还要完整动作复核。

## 四、最后报告和 Git

在上述输出目录保存 `V1_V2_3_1_VIDEO_COMPARISON_REPORT.md`、`segment_manifest.json`、视频与关键帧、来源 SHA256、FFmpeg 命令、V1 历史成片存在性、明确的裁切完整性结论、需用户看的优先文件。

同步简短报告到开发分支的 `10.27scasual_chain/docs/`（不要写入无法公开的私有视频数据）。只对审查脚本或报告正常 commit/push，**不修改 V1/独立 8.31，不改 V2 当前结果或自动验收规则**。

保持：

```text
render_ready=false
visual_qc_pass=false
blocked_source_corruption=true
```

**这不是 R2.10 重剪授权。没有看到可复核的 V1/V2 对照片段之前，不解除 3:1 硬阻塞。**
