# V3-P2 — Narrative Completion + Targeted Critical Evidence

**Branch / SHA:** `story-va-v3-plan2` (see push HEAD)  
**Worktree:** `/data2/lpy1/worktrees/migu-story-va-v3-plan2`  
**Baseline:** `d1364a4`  
**Outputs:** `.../v3/plan2/{A,B}_*_run03` (+ `_evidence`, `_gate`); run02 preserved  
**API=0 · render_ready=false · agent_auto_verified=0**

## 1. What was wrong after run02

V1 `compose_story_plan` **was already** emitting 铺垫/蓄力/转折/高潮 **plan segments** from score milestones + hydrated buildup. But V3 `story_view.recognition.beats` left 铺垫/转折/高潮/收尾 **empty**, so “Graph PASS” looked like story complete while the **story semantic interface** to V1 was incomplete. Buildup also admitted low-editorial events (Pass / Throw_in / Ball_possession).

## 2. V3-only fixes

| Module | Change |
|--------|--------|
| `narrative.py` | T01 beat assembly: narrative_placeholder goals (no fake `goal_action_sec`); editorial 蓄力 ranking; conservative 收尾; `narrative_completeness_report` |
| `pipeline.py` | Wire narrative story_view + completeness JSON; keep unresolved EDL goal slots |
| `targeted_evidence.py` + `evidence_cli.py` | Finite retrieval from G2.2 historical clues + pre-confirm blocks; continuous clip/frames; evidence pack → V3/V2 gate |
| `test_pipeline.py` | Assert five beats + placeholders; synthetic 蓄力 fixture |

No V1/V2/8.31 edits. No gold/causal. No hardcoded match PTS in ranking (B ~3130 window used only as **historical clue path** + agent audit note).

## 3. run03 narrative results

### A 阿联酋–阿曼
- Arc: left / 0:1→1:1→2:1 · predictions 79/0  
- Beats: 铺垫/蓄力×5/转折/高潮/收尾 all populated  
- 蓄力 (predicted strips → V1 plan): Shot/Save/Dribble_past from strip_clip{11,18,29,31,53}  
- Goal actions: unresolved placeholders (`media_in/out/goal_action_sec=null`)  
- Gates: **graph PASS · story semantic PASS · critical video FAIL**

### B 奥萨苏纳–塞尔塔
- Arc: **right / Celta** last deficit 2:1→2:2→2:3 (not left earlier arc) · 65/0  
- Beats complete; 蓄力 includes Shot + Dribble_past (+ weaker aerial/referee rows still present when Shot density low)  
- Same unresolved goal placeholders  
- Gates: **graph PASS · story semantic PASS · critical video FAIL**

`narrative_completeness_report.json` verdict both matches: `narrative_roles_ready_evidence_pending`.

**收尾 note:** recognition includes conservative final-score placeholder; V1 may omit duplicate scoreboard wrap when final board == go_ahead board (no fabricated whistle).

## 4. Targeted evidence (3 roles / match)

Order: B `opening_deficit` first (G2.2 clue **3128.32–3153.32** ≈ user 3130–3135), then expand.

| Match / Role | Top candidate PTS | Agent note | Gate |
|--------------|-------------------|------------|------|
| B opening | 3128.32–3153.32 | Board still **1–1** @45:06+3; corner/box then Osasuna celebration-like; **no clear continuous net**; 2:1 confirm ~3199 | reject `not_unambiguous_first_live` |
| B eq / go_ahead | historical earlier scenes | packaged unresolved | reject |
| A all three | G2.2 earlier/live-shot windows | packaged unresolved | reject |

Evidence pass reports: `n_video_verified=0`, `n_agent_auto_verified=0`, `n_human_video_supported=0`.  
`human_video_supported` ≠ `agent_auto_verified` — neither claimed.

## 5. Separate gate judgments (required)

| Gate | A | B |
|------|---|---|
| Graph structure | **PASS** | **PASS** |
| Story semantic (roles + predicted strips in plan) | **PASS** | **PASS** |
| Critical video evidence | **FAIL** | **FAIL** |

Cuttability: scoreboard anchors and buildup have candidate times but **blocked/unverified**; critical goals **forbidden in cut**.

## 6. Tests

```bash
PYTHONPATH=10.27scasual_chain/algo python3 -m unittest story_video_agent_v3.test_pipeline -v
```
**7 OK.**

## 7. Honest answer

**Has V3 built a cuttable complete story from frozen 8.31 strips?**  
**Partially.** It now builds a **real T01 narrative framework**: last-deficit arc, five beat roles, predicted-strip 蓄力 that V1 actually consumes, unresolved goal placeholders that do not fake action PTS. That is **story scaffolding with editorial meaning for buildup**, not a deliverable cut.

**Remaining video bottleneck:** contiguous **first-LIVE shot→net** for the three critical goals (plus attacking-team + identity-bound media). Historical windows (including B ~3130) are **clues**, not verified goals. No paid VLM / no auto-render until that evidence exists.

**Next:** human or authorized dense visual QC on the three slots/match only; keep `render_ready=false`.
