# Phase 4E — 第一轮静态审查（已执行；不含视频画面验收）

基准：`story-va-phase2c@e69b68f`，数据来源为 `phase4d_croatia_candidate_edl.json`、`phase4d_croatia_plan.json`、`phase4d_cut_quality_checklist.json` 和 `phase4d_verification_packets.json`。
本次只审查 GitHub 已提交文本、窗口与门禁，没有访问服务器私有原片或本地审核 MP4；以下**不构成人工视觉核验**。无付费 API、无权限签发、未合并 main。

## 1. 7 段时间窗的静态结果

| 顺序 | Story role | media_in | media_out | 源区间长度 |
|---|---|---:|---:|---:|
| 1 | deficit_scoreboard_anchor（铺垫） | 1075.06 | 1087.06 | 12.0s |
| 2 | buildup_attack（蓄力） | 3038.00 | 3064.00 | 26.0s |
| 3 | equalizer_goal_action（转折） | 3063.50 | 3075.00 | 11.5s |
| 4 | equalizer_scoreboard_anchor（转折比分） | 3141.98 | 3153.98 | 12.0s |
| 5 | go_ahead_goal_action（高潮） | 3518.00 | 3532.00 | 14.0s |
| 6 | go_ahead_scoreboard_anchor（高潮比分） | 3594.00 | 3608.00 | 14.0s |
| 7 | ending（收尾） | 7928.00 | 7942.00 | 14.0s |

源区间长度合计 **103.5s**；这不是对最终预览时长的媒体探测结果，实际时长须用 `ffprobe` 核实。

## 2. 发现的问题（不得静默标记通过）

- **P1：蓄力与转折源区间重叠 0.5s**，3038–3064 接 3063.5–3075。`phase4d_cut_quality_checklist.json` 明确报告 `ok=false`。现场看镜头后确认：调整切点、保留有意交叠并解释设计，或采用正式交叠转场；不得称所有邻接检查已通过。
- **P1：比分叙事断层**，展示 2:1 反超后直接 FULL TIME 4:1，没有 3:1 和 4:1 的动作或有解释的蒙太奇。须提出补片或叙事过渡，并让用户在预览中审查选择。
- **P2：得分动作后隔一段才显示确认牌**。扳平动作结束至 1:1 牌开始约 **66.98s**；反超动作结束至 2:1 牌开始 **62.0s**。源时间间隔不等于最终剪辑视频中的黑场，但二者要检查镜头切换是否自然。
- **P2：音频未经正式质量审核**：原报告明确 preview 按源音频切段，尚无响度统一。须核对各段 LUFS / true peak、接缝、现场声和静音。
- **P2：收尾 `FULL TIME 4-1 @≈7935` 是本地观察候选**，尚待检查截图与完整连续片段是否对应最终比分、终场哨和收尾镜头。
- **P0（生产门禁）**：两次进球核验包仍为 `pending_independent_human_review`；全部 7 段 `candidate_only`，`render_ready=false`、`render_ready_edl=[]`。禁止未经 `human_audited_review` / `independent_verification_pipeline` 签发而生产。

## 3. Phase 4E 离线操作验收条件

1. 在服务器上用 `ffprobe` 复核预览：实际时长、分辨率、帧率、音轨、黑帧/空白、7 段均有画面；记录可复查的 manifest。
2. 用 FFmpeg 对**每个**视频切换点生成前后 1–2s 的 contact sheet / 审核短片，尤其是 3063.5–3064 重叠，且记录是否重复动作、异常跳切、音轨断裂。
3. 对 3:1、4:1 追加镜头至少给出两套候选：A 保留短版并加清晰文字桥接；B 按事件/因果信息和本地视频追加得分动作形成更完整翻盘故事。只做本地搜索，不调用付费 API。
4. 审核包覆盖两次入网和 7 段，逐段保留来源、requested/actual PTS、直播/回放、画面证据、未解冲突；原始视频和截图放 `_local_render`，不要提交 GitHub 大文件。
5. 导出至少一版可播放的正式**审核预览**，并以可让用户在 Cursor/服务器中打开的路径+准确播放器命令提供。它仍是 preview，不是 final。
6. 只有所有审核文件可访问、7 段 QC 报告存在、审核视频可实际打开时，方可将 `phase4e_review_status.json` 中的 `requires_user_review` 改为 true，并列出精确需要用户判定的事项。不能以 Mock/模型自信分数冒充独立签发。
7. 如自动检查失败，保持 review_ready=false，附带失败原因；禁止假设成功。

## 4. 用户人工审核点

请用户明确审阅：①扳平 live 入网镜头及切点；②反超 live 入网镜头及切点；③2:1→4:1 是补片还是文字桥接；④五段故事连贯性与时长；⑤终场 4:1 与音视频切换质量。用户审核决定不自动等价于生产授权，须经现有正式核验流程落盘并校验。
