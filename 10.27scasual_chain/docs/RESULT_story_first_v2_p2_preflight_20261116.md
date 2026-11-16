# Story-First V2 P2 零付费实片预检（H5 源证据）

代码：`ba38ef7205ba1fd15720a459c2ccbd46fe3afa3d`  
对照运行：`e0c68ea` / `/tmp/lpy1_story_first_v2_paid_round1_20261116/`（只读复用）  
本轮产物：`/tmp/lpy1_story_first_v2_p2_preflight_20261116/`  
**API 调用：0**（无 Generator / Scorer / Planner；无正式 EDL/BEST/全量重渲）

## 1. Pytest 与 SHA

| 项 | 结果 |
|----|------|
| HEAD | `ba38ef7205ba1fd15720a459c2ccbd46fe3afa3d` |
| Story-First + continuous_broadcast 回归 | **74 passed** |
| 付费调用 | **0** |

## 2. H5 三事件：真实性与球队归属

复用绑定：`event_000634/635/636`，窗口 `[6395.81, 6418.07]`。

| 事件 | PTS | 直播标注 | 回放/慢放 | notes | attributes（攻/防） | 场地 | 离线结论 |
|------|----:|----------|-----------|-------|---------------------|------|----------|
| 634 | 6403.81 | LIVE | 否/否 | 1队截获2队传球 | 攻2队 / 防1队 | Midfield_Third | **事件存在且自洽** |
| 635 | 6405.03 | LIVE | 否/否 | 2队截获1队传球 | 攻1队 / 防2队 | **Defensive_Third** | **事件存在；对方反抢** |
| 636 | 6410.07 | LIVE | 否/否 | 1队截获2队传球 | 攻2队 / 防1队 | Midfield_Third | **事件存在且自洽** |

画面抽帧（同 PTS）：比分牌 **UAE 0–1 OMA @75:11–75:17**；红衣=阿联酋、白衣=阿曼；**未见 REPLAY/SLOW 角标**。notes 与 attributes 在「谁抢谁」上一致（交替 1→2→1）。  
1队/2队与红白队的**故事主角映射**仍须在付费核验中显式对齐；不能仅凭帧包宣称 FIRST_LIVE。

## 3. H5 关系是否成立

声明：`连续拦截后球权转换或导向扳平进攻`（`interval_01:H5:r1`）。

**离线结论：不成立为「扳平进攻组织起点」。**

依据：
- 三次拦截球队**交替**，不是主角连续夺权。
- 635 场地为防守三区，与 634/636 中场不一致。
- **6410.07 → 6436.924 无人工原子事件**；约 32s 空窗。下一组目录事件是 `atom_fill` Pass/Assist/Shot/Goal（6442.87→6449.64），**不在 H5 引用集**。
- 修订后 `source_followthrough` 帧 ~6423.76（75:30）仍见**白衣持球向阿联酋半场推进**，与「夺权后导向扳平」持续进攻读法冲突。

**更准确的故事解释：**  
`0-1 落后阶段的中场连续球权转换/拉锯快照（含一次对方反抢）`；若服务扳平叙事，需另选能覆盖 6410→6443 连续推进的事件链，或放弃因果、只保留局部态势。

Fixture 零付费核验（正确引用事件绑定帧）亦仅将关系标为 **UNCERTAIN**；三事件可过 SUPPORTED 校验路径。

## 4. FIRST_LIVE 状态与缺口

| 项 | 状态 |
|----|------|
| 上轮本地帧包 | `FRAME_BOUND_VALID` |
| `first_live_verified` | **false** |
| `frame_pack_cannot_certify_first_live` | **true** |
| `event_chain_insufficient` | **true** |
| ledger 新窗口 | 仍为空（上轮未入账） |
| 原子 `broadcast_phase` | 三者均为 LIVE（**不等于**首次直播认证） |

**缺口：** 无独立连续播出时间轴审查包入账；三事件共用粗窗口 `[6400.9,6412.5]` 不能当逐次首次出现证明；源核验设计上**不能**签发 FIRST_LIVE。

## 5. 修订后核验输入规模与输出上限（ba38ef7）

干跑 `_story_review_frames` + 组装 `review_input.json`（本地解码，无 API）：

| 角色 | PTS 样本 | 含义 |
|------|----------|------|
| **before** | 4710.08 / 4714.88 | 当前 EDL `seg_buildup_event_000472` |
| **candidate** | 6402.52…6411.40（含三事件精确 PTS） | 候选插入窗 |
| **after** | 6443.56 / 6452.36 | 当前 EDL `seg_equalizer_goal_action` |
| **source_leadin** | 6381.84 / 6389.84 | 候选前 20s 原片过程 |
| **source_followthrough** | 6423.76 / 6431.28 | 候选后至 equalizer `media_in`（覆盖空窗） |

- 帧数：**13**；均 `pts_status=pts` 且落在各自窗内。  
- fit 仅使用 before/candidate/after；leadin/followthrough **不进入** edit-fit triplet。  
- Prompt 文本 token（tokenizer 估）：**1451**（旧 2241，约 −35%）。  
- 紧凑样例响应：**~274** tokens；旧截断响应顶满 **1200**。  
- Provider 默认 vision completion 仍为 **1200**；按 4–12 词/字段的新 schema，**单次核验应能避免 length**（仍建议实呼前确认 `token_limit_sent≥1200`）。  
- 事件与关系**分行**返回；fixture 路径已跑通评估逻辑。

## 6. 是否具备一次真实源视频核验条件

**具备（有条件）。**

可做：
- 复用已绑定 `interval_01:H5` trial（勿重跑 Generator/Scorer/Planner）
- 用 `ba38ef7` 发 **一次** 源视频核验，核对事件/关系/edit-fit

仍不可直接进 P3 试剪，除非另补：
- 独立 FIRST_LIVE 证据入账
- 且核验未因 truncation/归属错误整体失败

预期付费核验：事件或为 SUPPORTED；关系大概率 **UNCERTAIN**；FIRST_LIVE 仍需另通道。

---

独立结论机读：`docs/artifacts_story_first_v2_p2_preflight_20261116/P2_INDEPENDENT_CONCLUSIONS.json`  
**停止于零付费预检，等待下一步付费授权。**
