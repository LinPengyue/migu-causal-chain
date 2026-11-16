# Story-First v2 开启侧单轮实跑（2026-11-16）

HEAD: `d3eb826fe674bbef3a9c97d6a91c132240f52375`  
Server out: `/tmp/lpy1_story_first_v2_paid_round1_20261116/`  
Artifacts: `docs/artifacts_story_first_v2_paid_round1_20261116/`  

授权：单轮、`--max-calls 8`、`--max-cost-usd 0.10`；复用 Causal-4 `interval_01`；`--build-local-first-live-evidence`；**不做关闭侧对照**。

## 费用与 HTTP

| 角色 | calls | est_usd | 备注 |
|------|------:|--------:|------|
| vision（Critic） | 1 | ~0.0023 | 成片抽帧诊断 |
| story_first_generator | 1 | 0.00254 | interval_02，Flash，prompt 12757 / out 1044 |
| story_first_scorer | 1 | 0.00278 | interval_02 Causal-4 |
| revision_planner | 1 | 0.00256 | DeepSeek-V4-Pro，见全部 10 候选 |
| vision（源视频 trial 核验） | 1 | 0.00392 | **finish_reason=length**，token_limit=1200 |
| **合计** | **5 / 8** | **0.014092** | 未触达费用上限；剩 3 次未用于 Verifier（无试剪） |

`vision.output_budget_exceeded=true`（第二次 vision）。

## 候选池

| 区间 | 状态 | 候选 |
|------|------|------|
| interval_01 opening→equalizer | REUSED | 5（历史 Causal-4） |
| interval_02 equalizer→go_ahead | **GENERATED + SCORED** | 5 |

Planner 输入 **10** 条；含机制/不确定性；**无数值分**。

### interval_02 摘要（生成侧）

| ID | prior | 摘要 |
|----|------:|------|
| H3 | 0.425 | 终场前任意球/争顶/射门 → 定位球施压 |
| H4 | 0.425 | 争顶+长传铺垫领先 |
| H5 | 0.363 | 犯规→任意球→射门 |
| H2 | 0.288 | 对方连续化解（防守链） |
| H1 | 0.250 | 连续射门被扑后直至破门 |

## Planner 选择（核心）

- 正式决策：**UNRESOLVED**（无 revision 成片编辑；`mark_unresolved` 仅标记未观察 ending）。
- **提出了 `story_first_trial`**：选中 **`interval_01:H5`**
  - 事件：`event_000634/635/636`（6403.81–6410.07s 三次拦截）
  - 关系：`r1` state_transition「连续拦截后球权转换或导向扳平进攻」
  - 窗口：`[6395.81, 6418.07]`，拟插在 `seg_buildup_event_000472` 之后、`seg_equalizer_goal_action` 之前
- 选择理由（摘要）：最紧凑、最靠近扳平建起；非 replay；可直接观察最后一次拦截是否导向扳平进攻。排除 H1（VAR replay）、H2/H4（跨队）、H3（缺攻防交错）；认为 interval_02 与同阶段联动更弱。

→ **真实 Planner 能从双区间候选中选出一条具体、可绑定 PTS 的故事试验。**

## 源视频核验结果

程序状态：`story_first_trial_status=NEEDS_REVISION`。

| 结论 | 原因 |
|------|------|
| `AWAITING_VIDEO_REVIEW` | 源核验响应 `finish_reason=length`（1200 completion 触顶）→ `video_review_not_real_or_truncated` |
| `NOT_VERIFIED` | 无独立 FIRST_LIVE evidence pack（仅有本地绑定帧包） |
| `NEEDS_VIDEO_REVIEW` | missing_triplet_review |

按协议：**未进入临时 EDL 试剪 / 双视频 Verifier**（`apply` skipped；ledger `windows=[]`）。

### 已保留的原片上下文（缺 FIRST_LIVE 时）

目录：`…/story_first_source_review/story_first_ab22f01929b5cb4f59e6badd_01/`

- `context_clip.mp4`（约 45MB，服务器保留）
- 绑定帧 3 张 + `evidence.json`（`FRAME_BOUND_VALID`，`first_live_verified=false`）
- `broadcast_timeline_review.json`（binding_only，outcome UNKNOWN）
- before/candidate/after 抽帧 9 张（manifest）

### 截断响应中的可用信号（非正式验收，供调参）

在被拒收的 `review_response.txt` 里，模型已写出：

- 三事件均为 **SUPPORTED**（白→红→白拦截交替，帧对齐注释）
- 关系 **UNCERTAIN**：交替抢断可见，但到扳平建起（~6443s）的因果未证；candidate→after 跳过约 32s
- before 帧落在 **~4710s**，与 75 分钟候选窗口严重脱节（核验文本已指出 baseline 不当）

这些内容因 length 未进入正式反馈结构；下一步应提高源核验 completion 上限或压缩核验 schema，并修正 before 上下文选取。

## 未做 / 下一步

- 无关闭侧对照（按本轮范围）。
- 无有证据支持的试剪成片可供人工对照。
- 建议下一刀：在已有 trial 绑定与帧包上，**(a)** 修源核验截断 / before 上下文，**(b)** 补独立 FIRST_LIVE 审查，再决定是否试剪；interval_02 候选已在池中可复用，无需重生成。

不修改正式 EDL / BEST / v1。不做质量达标宣称。
