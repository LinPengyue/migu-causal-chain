# 故事链 / Video Agent 交接上下文

新对话做故事链或 Video Agent 时先读本文件。代码改动只在本目录 `10.27scasual_chain/`，不要改 `8.31causal_chain/` 与 `10.19scasual_chain/`。

## 目录关系

- 源：`/data2/lpy1/causal-chain2/8.31causal_chain/`（咪咕 2.3–2.6 协议 RC，保持不动）
- 故事链副本：`/data2/lpy1/causal-chain2/10.19scasual_chain/`（2026-10-19 复制；逆风翻盘 T01 规则版已在此落地，保持不动）
- 本目录：`/data2/lpy1/causal-chain2/10.27scasual_chain/`（2026-10-27 从 10.19 整份复制；后续 Video Agent 研究在这里开发）
- 复制时已排除 `__pycache__`、`.pytest_cache`、`.venv-api`

## 已有能力（不要重做）

足球拆条因果链 + 集锦因果链，不是故事片。

- 拆条：局部事件序列，分成结果/修正/险情/特殊，再映射到固定子类型（扑救、进球、乌龙、红牌等）。
- 集锦：`algo/causal_chain8/link_strip_chains.py`。链与链之间只有三种边：
  - `follow`：时间连续
  - `same_sequence`：同一次攻防
  - `correction_of`：VAR/改判修正前一条结果
- 编排仍按比赛时间。代码写明不编造球队、比分。
- 这就是产品所说的「普通流水集锦」。故事链是它上面的新层，不要改这三种边的定义。

协议层 `api/`（`/highlight/start|sync|end` + 出站 callback）是咪咕联调，与故事链算法无关。故事链第一期不必改协议。

## 产品需求 vs 标注（已对齐的结论）

产品经理描述的是业务场景，不是可直接编码的规格。实现必须落在已有标注上。

产品要的故事链：围绕一条主线，片段有因果/情绪递进（铺垫→积累→高潮→收尾），可以为主题丢掉无关高光；战局类多数仍按时间，人物/主题类才允许打乱时钟。三类主线：战局剧情（逆转/绝杀）、人物命运、对抗博弈。

明确不做（标注里没有）：人脸、球衣号码识别、解说语调、欢呼声、反应镜头/过渡镜头。`video.has_audio` 只表示有音频，没有音频标注。

## 标注实际在哪、有什么字段

`datasets/` 里的金标不能直接做故事链。构建脚本 `scripts/build_datasets.py` 从交付 JSON 抽金标时丢掉了人、比分、情绪分。

- `datasets/strip_gold`：437 条。字段只有类别、子类型、起止时间、事件 `{type, type_raw, t_ms, event_id}`。子类型最多的是射门扑救链 160、其他 83。乌龙球致因链 3 条，终点事件类型已改成 `own_goal`（词表在 `algo/causal_chain2/chain_schema.py` 的 `EVENT_TYPES`）。
- `datasets/highlight_gold*`：T0/T1 选片窗（no_t2 共 144），按时间堆高光，没有叙事角色。
- 63 场。

故事链要用原始交付，路径：`data/交付_out/`。

1. 全量事件 JSON（约 67 个）：`events[]`
   - `attributes.Score_Recognition` / `scores.score_recognition`：比分字符串，如 `0:1`（抽查一场约 542/550 有）
   - `scores.emotional_heat_score`、`criticality_score`、`overall_score`、`technical_difficulty_rating`：同一格里排序用，不决定主题
   - `attributes.BallController_team`、`BallController_player`、`Related_Player`：阵营/球员。球员 ID 不齐，有 `team_1_player_7`，也有「2队队员」
   - `attributes.Pitch_Area`、`Shot_Type_Camera_Angle`、`Match_Phase`
   - `notes`：自由文本，只能辅助
   - `teams`：队名、球衣颜色
   - `video_context.is_replay`
2. 因果链 JSON（63 个，`*_causal.json`）：`causal_chains[]`
   - `chain_category`、`causal_chain_subtype`、`is_replay`、时间、链内事件（类型 + `event_id`）
   - 没有主题、没有铺垫/高潮标签、没有球员、没有比分

用 `event_id` 把全量事件上的比分/球员/情绪分贴回因果链。

## 三类主线怎么落到标注（讨论结论，尚未写代码）

1. 战局剧情链：先做。进球按时间排，用 `score_recognition` 看落后→追平/反超。落后阶段的扑救、门线、射门不进当作铺垫；改变领先关系的结果链当作转折/高潮；最后一粒改变领先关系且落在后段的进球当作绝杀。不改变比分轨迹的高光丢掉。顺序仍用比赛时间。
2. 人物链：只用 `BallController_player` 稳定的人。ID 模糊（「2队队员」）的场次跳过，不用全队进球冒充。
3. 对抗链：双方进球交替，依赖 `BallController_team`。该字段覆盖低（抽查约 59/550）时主线不成立。

主线都不成立时，退回现有流水集锦，并标明「无故事」。

没有「这场故事片该留哪几段」的金标。自动评测只能核结构：一条主线、高潮格确实改变比分、丢掉的片段不在该比分轨迹上。观感要另标小批故事片金标。

## T01 逆风翻盘：两层输出（2026-10-20 约定）

按产品理解，**比分上落后后再反超本身就属于逆风翻盘剧本**。时间序列里的铺垫/蓄力是叙事完整度，不是剧本门槛。

算法因此做两层，不要混成一层「有/无」：

1. **story（严格）**：比分轨迹 `落后 → 扳平 → 反超`，且时间上有铺垫（失球/扑救/门线）和蓄力（至少两次射门/任意球/角球）。`has_story=true`，`story_label_zh=逆风翻盘`，出完整故事链。
2. **candidate（候选）**：比分翻盘成立，但缺铺垫或蓄力（典型：克罗地亚开场即 `0:1`，文件里没有失球镜头）。`has_story=false`，`is_candidate=true`，`story_label_zh=逆风翻盘候选`，仍输出以扳平/反超为主的事件序列，供人工或下游筛选。
3. **none**：连稳定比分翻盘都不成立 → 无故事、无候选。

实现入口：`algo/story_chain/`（`recognize.py` 定 tier，`end_to_end.py` 端到端）。输出目录默认 `reports/story_t01/`。

## 实现约束

- 不改 `causal_chain8` 链间边的语义；故事层在拆条链之上选主题和格子。
- 不在算法里编造缺失的比分、球队、球员。
- 5 分钟出片取决于上游事件是否到齐；规则引擎本身不是瓶颈。
- 本目录协议服务启动仍要 Python 3.9+ 与 `api/`（`start_api.sh` / `.command` / `.bat`，依赖 `requirements-api.txt`）。与故事链算法无关。

## 不要继承的误解

- 产品清单里的人脸、音频峰值、反应镜头，不是本包能力，也不在标注里。
- `datasets/` 金标的 `label_score` 是选片打分，不是情绪分。情绪分只在 `交付_out` 的 `scores.emotional_heat_score`。
- 乌龙在事件层是 `own_goal`，链模板是 `own_goal_causal_chain`（chainType 14）。金标里只有 3 条。
