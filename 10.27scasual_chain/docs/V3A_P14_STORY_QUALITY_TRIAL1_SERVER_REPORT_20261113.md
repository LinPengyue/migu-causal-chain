# P14 Story Quality Trial 1 — server evidence report

Branch: `story-va-v3a-p14-story-quality-20261113` @ `ffc90b3`  
Helper: `docs/v3a_p14_story_quality_review.py`  
Out: `/tmp/lpy1_v3a_p14_quality_review_20261113/`  
Base run: `/tmp/lpy1_v3a_p14_cv_integration_20261113/run` (EDL/MP4 **unchanged**)

## Execution

```bash
python -m py_compile docs/v3a_p14_story_quality_review.py  # ok
python docs/v3a_p14_story_quality_review.py \
  --run-dir /tmp/lpy1_v3a_p14_cv_integration_20261113/run \
  --source-mp4 '…阿联酋VS阿曼 国语.mp4' \
  --out-dir /tmp/lpy1_v3a_p14_quality_review_20261113 \
  --max-per-issue 2
```

| Gate | Result |
| --- | --- |
| paid_http | **0** |
| edl_modified | **false** |
| story MP4 SHA | `7764010f…` (~94.877s) unchanged |
| EDL SHA | `b38434b9…` unchanged |
| Integration/C fingerprints | unchanged |
| first_live / semantic defects verified | **false** (by design) |

Acceptance pack: 3 finished-story context MP4s + 4 event-PTS source candidates (ending had **0** search hits).

## Visual audit (finished-cut first)

### 1) `…deficit → buildup` (seam story≈28.5s)

| Sample | Clock / score | Content |
| --- | --- | --- |
| before | 11:39 / 0–1 | crowd / “失球·落后开始” |
| seam | 12:45 / 0–1 | midfield “铺垫” |
| after | **46:57** / 0–1 | UAE box attack “蓄力” |

Large clock jump (≈12′ → ≈47′) is real, but the next beat remains readable: still behind → building an attack. **Not incomprehensible.**  
Event candidates (~3504s / ~2273s) are mid-first-half actions; inserting them would be a generic bridge without proven missing causal/emotion info.

**Verdict: `DEFECT_REJECTED` (KEEP_COHERENT).** No one-edit.

### 2) `…buildup → equalizer_goal_action` (seam story≈40.5s)

| Sample | Clock / score | Content |
| --- | --- | --- |
| before | 47:01 / 0–1 | GK “蓄力” |
| seam | 47:05 / 0–1 | referee signal |
| after | **75:47** / 0–1 | wide play “转折·扳平” → equalizer package |

Possible **false-causality** montage (47′ attack appears to lead into 75′ equalizer). Equalizer beat itself is still understandable from the goal action that follows.  
Search candidates (~4755 / ~4781, still ~47′) **do not** supply late pre-equalizer first-live connective tissue; they cannot fix that montage concern.

**Verdict: `EVIDENCE_INSUFFICIENT` for a safe one-edit** (concern noted; candidates unfit).

### 3) `thin_post_climax_tail` (last ~20s)

| Sample | Content |
| --- | --- |
| early/mid | 82:26–82:34 / 1–1 climax “高潮·反超” action |
| late | wrap title card “阿联酋 逆转 阿曼 / 2:1 / 故事收束” |

Story reaches explicit wrap. No source candidates exported. Abrupt post-goal aftermath is stylistic, not proven missing emotion that blocks comprehension.

**Verdict: `DEFECT_REJECTED` / insufficient evidence for insert.** (Avoid Phase4-style ending insert before earlier scoreboard.)

## Trial-1 decision (next Agent edit?)

**Do not authorize Planner→Executor one-edit yet.**  
No issue has both (a) independently confirmed narrative defect and (b) a continuous first-live candidate that shows the missing information.

Closest optional story target for a *future* bounded paid/semantic review: issue‑2 montage causality — but that needs equalizer-adjacent source evidence, not the current EVENT_PTS hits.

This report does **not** claim story-quality improvement; it only delivers watchable review clips + honest defect status.

## Clip paths (server)

- `/tmp/lpy1_v3a_p14_quality_review_20261113/01_finished_story_context.mp4`
- `/tmp/lpy1_v3a_p14_quality_review_20261113/02_finished_story_context.mp4`
- `/tmp/lpy1_v3a_p14_quality_review_20261113/03_finished_story_context.mp4`
- event candidates `01_event_candidate_{01,02}.mp4`, `02_event_candidate_{01,02}.mp4`
- Docs mirror: `docs/p14_story_quality_trial1_20261113/` (manifest + audit frames; MP4s stay in `/tmp`)
