# STORY_VA_V2 G0 — Decision

## One-line answer

**不能直接换视频跑正式跨场推理/成片：** 事件适配与比分轨迹有通用基础，但最终 EDL（固定五球 + 克罗地亚 PTS）、CLI 默认 R22/校验缓存、以及「首次落后」主角逻辑会在 A/B 上失败或串场；须先完成下列 G1 最小改造。

## G1 前必须修（P0）

1. **缓存/默认隔离：** 去掉或门禁 `DEFAULT_R22` 克罗地亚路径；`--reuse-verify-cache` 绑定 `match_id+video_sha256+events_sha256+strip_provenance`；拒绝 mismatch；拒绝 `*_causal` / gold 文件名。  
2. **通用 N 球 EDL：** 新 composer；禁止 A/B 调用 R2.6–R2.9 克罗地亚硬编码。  
3. **Last-deficit 弧 / 右侧主角：** 扩展 `v2_score_transitions`（或并列 API），修正 B 场 2:1→2:3 右翻盘。  
4. **缺失进球恢复为默认路径：** A/B 几乎无 typed Goal；未核实则 `unresolved`，不伪造 verified、不升 `render_ready`。

## 可暂缓（P1）

- OCR 噪声 hardening、非进球 strip 数量策略、Live-Only 联赛差异、动态标题文案、历史 strip_dump 是否可复用（优先新跑或打 provenance）。

## G1 最小执行顺序

1. Implement P0 isolation + path guards (no paid API).  
2. Implement `last_deficit_arc` + generic EDL skeleton (unit/synthetic).  
3. **Stop/Go A:** with explicit `--match-id/--r22-dir`, dry-run through planner→generic EDL on UAE–Oman using **raw events only**; budgeted API only if approved; **`render_ready` stays false**.  
4. **Stop/Go B:** same for Osasuna–Celta; assert protagonist_side=right on last arc.  
5. Optional France; real N only when MP4 exists.  
6. Human QC before any `render_ready` discussion.

## Stop / Go

| Gate | Stop if… | Go if… |
|------|----------|--------|
| G1 start | Any P0 still open | P0-1…4 coded + Croatia R2.9 freeze unchanged |
| After A dry | Cache hit from Croatia; causal/gold used; EDL assumes 5 goals; unresolved goals marked verified | Provenance clean; 3-goal EDL builds; `render_ready=false` |
| After B dry | Protagonist=left from first arc only | Last-arc right selected or explicit partial with reason |
| Render/API | User did not approve budget / still on G0 constraints | Separate explicit task |

## G0 deliverables checklist

- [x] `STORY_VA_V2_G0_ARCHITECTURE_AUDIT.md`
- [x] `STORY_VA_V2_G0_MIGRATION_BLOCKERS.md`
- [x] `STORY_VA_V2_G0_MATCH_MATRIX.md`
- [x] `STORY_VA_V2_G0_INTERFACE_CONTRACT.md`
- [x] `STORY_VA_V2_G0_DECISION.md`
- [x] Optional isolation: `v2_g0_cross_match_preflight.py` + unittest (11 OK)
- [x] No cross-match inference / paid API / new video / V1 / 8.31 edits

## A/B data bottom line

- **A:** MP4 ✅ + raw events ✅ + causal/gold present but forbidden; 3-step left comeback; ready for G1 **after** P0.  
- **B:** MP4 ✅ + raw events ✅; right last-arc needed; current score API wrong for T01 intent.  
- **N (Qatar–UAE):** no MP4 — not a video negative.
