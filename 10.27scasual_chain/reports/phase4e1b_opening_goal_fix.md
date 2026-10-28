# Phase 4E.1b — 补齐加拿大开场失球（翻盘起因）

**分支：** `story-va-phase2c`  
**相对：** `ed1f82b`（Phase 4E.1）  
**门禁：** `candidate_only`，`render_ready=false`，无付费 API

---

## 1. 问题

ChatGPT 复审：长版只有克罗地亚四球 + 0:1 记分牌，**缺少真正造成落后的加拿大进球过程**。  
`score_path` 0:1 @1079.06s 仅为后续比分确认，不能替代动作。

因果线索（`data/交付_out/2022-11-28 克罗地亚vs加拿大_causal.json`）：

- `ann_0001`，`is_replay=false`
- 传球 969.094 / 973.683 / 978.783s
- `event_000004` Goal @ **980.137s**

---

## 2. 本地画面定位（960–995s）

| media_t | 画面 |
|---------|------|
| ~978 | 禁区进攻，牌仍 0:0，直播 |
| ~980.0–980.5 | Davies #19 冲顶 |
| **~981.5** | **球进网**（守门员扑空）；牌仍 0:0（滞后） |
| ~984–990 | 庆祝（live） |
| 1079 | 记分牌 0:1 + DAVIES 2' 条（确认，非动作） |

**剪辑窗：** `968.0–990.0`（传球→头球→入网≈981.5→庆祝）。  
不把 980.137 标注入网终值；入网以画面 ≈981.5 为准。

---

## 3. 通用逻辑缺陷与修复

| 层 | 缺陷 | 修复 |
|----|------|------|
| `story_chain/recognize.py` | `concede_ids` **跳过 `opening` 节点** → 开场即落后永远 `missing_setup` | 保留 opening 失球 carrier |
| `story_chain/comeback.py` | `_GOAL_MATCH_BEFORE=90`，本场牌滞后 ~99s 匹配不到因果进球 | 升至 **120s** |
| `narrative_composer.py` | 铺垫只出记分牌，无对手进球动作段 | 新增 `seg_opponent_opening_goal_action`（先于牌） |
| `event_mapping.py` | story.events 常缺对手进球；交付 ID 与因果 ID 冲突 | `merge_causal_live_goals`（`causal:ann:…` 命名） |
| `state.py` `detect_gaps` | 未单列失球动作缺口 | `locate_opponent_opening_goal_action` |

回归：`story_chain.test_score_path` + `test_phase3a1`（含 Croatia+causal / 合成 opening）。

刷新后 T01 克罗地亚故事：`铺垫` 含 `event_000004` 进球；tier 升为 `story`（蓄力亦齐）。

---

## 4. 新长版叙事顺序

加拿大先进球 0:1 → 短牌确认 → 蓄力 → 扳平 1:1 → 反超 2:1 → 3:1 → 4:1 → FULL TIME

保留 4E.1：花屏避让窗、短牌、响度 ≈−16 LUFS、蓄力 abut 3038–3063.5。

---

## 5. 产物

见 `phase4e1b_review_status.json` 与 `_local_render/phase4e1b/`。
