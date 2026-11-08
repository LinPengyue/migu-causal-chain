# Phase 8 — Real-video zero-HTTP preflight and controlled quality-evaluation handoff

Status: RUNBOOK / NOT YET EXECUTED ON SERVER. Designed for existing V3-A branch story-va-v3a-phase8-loop-impl after merged PR #2 and source-video preflight script. Never use gold or manual story annotations as inference inputs.

## Goal

Stop building more Phase8 loop modules. Check the actual UAE–Oman original broadcast clips before any paid VLM trial. First-live must be demonstrated from original broadcast context, not inferred from event-chain LIVE, frame hashes, ordinary clip continuity, or a model assertion. The reviewer can explicitly decide UNKNOWN.

## 0. Pull and verify code

```bash
git fetch origin
git switch story-va-v3a-phase8-loop-impl
git pull --ff-only origin story-va-v3a-phase8-loop-impl
git rev-parse HEAD
git status --short
cd 10.27scasual_chain
PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_*.py -q
```

Preserve local edits and use a separate worktree if the target working tree is dirty. Report the actual passed/deselected counts; the latest hotfix tests were NOT independently run by ChatGPT.

## 1. Source footage and event provenance

Evidence in earlier committed fourth-audit proof references source MP4:

```text
/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4
```

Check this path actually exists on Cursor's server. **Approved input set: original `赛事.json` atomic events + supplementary `causal.json` atomic events + original source MP4.** User explicitly permits `causal.json` to fill missing atomic events and links in `赛事.json`; do not exclude it simply for being supplemental or manually curated. Preserve source-file/event IDs, input SHA, PTS and merge/deduplication decisions. This permission does NOT extend to `strip_gold.json`, benchmark answer keys, or human-labeled long-form story/EDL ground truth. If optional causal event schema differs, map its atomic events into the search input with documented lineage rather than discarding them. Event metadata never independently certifies FIRST_LIVE_VERIFIED; UNKNOWN remains valid without source-video broadcast proof.

## 2. Reproducible zero-HTTP source-context inspection

```bash
export SOURCE='/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4'
export OUT='/data2/lpy1/_story_va_outputs/v3/plan2/phase8_real_preflight_20261108'
test -f "$SOURCE" || { echo 'SOURCE MISSING'; exit 1; }
PYTHONPATH=algo python scripts/phase8_real_video_preflight.py \
  --source-mp4 "$SOURCE" --out "$OUT" \
  --window bridge_3504:3504.14:3515.83 \
  --window live_candidate_6430:6430:6445 \
  --window replay_candidate_824:824.81:835.15
```

For event-aware replay screening, optionally append `--events-json /actual/path/to/event_union.json`, where `event_union.json` may combine the user-approved `赛事.json` and `causal.json` atomic events. Record the exact two source paths, SHA values and merge adapter used. This optional argument expects the script's supported event-list schema; do not pass an incompatible raw `causal.json` without checking its structure. The script computes source SHA, cuts continuous original-source context clips with ffmpeg, records clip hashes and event overlaps, and writes `preflight_summary.json` and per-window `broadcast_timeline_review.json`. No provider calls, no automatic first-live positive, no edit/render loop.

Do not commit large context MP4s to Git. Provide their exact accessible server paths and content hashes, or upload short audit previews in the conversation for visual review. The source file must remain unchanged. If generated event JSON's structure cannot be loaded, report the real schema rather than changing production algorithms blindly.

## 3. Real first-broadcast evidence review

Review the ORIGINAL adjacent footage and where necessary earlier occurrences across the match timeline, not just three still images. For each proposed new segment record: first appearance? replay transition/overlay? slow motion? scoreboard and clock continuity? live camera sequence? whether clip is related to the intended story role? Mark FIRST_LIVE_VERIFIED only when evidence is strong and independently reviewed; REPLAY_CONFIRMED for grounded replay; else UNKNOWN. Any explicit positive certification requires reviewer identity or review method, referenced source/video SHA, exact window, cited continuous context and earlier occurrence checks.

Important: neither source-window binding nor a 30-second context clip alone proves no earlier occurrence. If no human/algorithmic full-timeline review is available, leave `UNKNOWN` and release_authorized=false. Don't include a mechanism fixture as match truth. The replay candidate should remain excluded; do not interpret the window label as truth without reviewing its actual evidence.

## 4. Next experiment after preflight (NOT APPROVED / do not pay)

Cursor should supply a budget estimate and exact existing V3-A invocation for one **controlled** 2–3-round Critic → Planner → Verifier test (first-live approved materials only). Ask for explicit user authorization of a total USD cap and call count before enabling `enable_real_api`/`i_approve_budget` or any `phase8_paid_multi_round` switch. Current approval does NOT cover a paid run; zero paid is mandatory in this handoff.

Freeze source MP4, initial V3-R EDL/MP4, `赛事.json`, permitted `causal.json` (if supplied), event merge rules, story template, version SHA, provider model, visual sampling and API budget. Run the same initial video as a single-round baseline with equal total observations/cost where feasible. For each round log diagnosis, selected issue, source PTS, prior feedback, evidence frames, candidate EDL, render file, safety outcome, soft story quality, best-vs-working comparison, budget and stop reason. Never infer story quality from the number of rounds or rejected clips.

## 5. Story-quality scoring after a real video is available

Required safety: no replay/slowmo, first-LIVE verified on all new footage, goals intact, EDL/MP4 aligned, no fabricated PTS. Those are constraints, not quality bonuses.

Compare initial and final videos blind if possible, using 1–5 anchored scores for narrative logic (buildup→turn→climax→resolution), continuity/causal clarity, clip transition smoothness and pacing, and whether each revision actually fixes an identified defect without introducing another. Human review and video evidence both required for delivery-quality claims. Report wins/losses, not just an average. Keep unknowns explicit. For generalization, repeat later on a genuinely unseen match and other story templates using the same code and rules; no match-specific heuristics.

## 6. Cursor return package

- Branch/HEAD (after PR #2 merge) and clean/dirty worktree status.
- Exact pytest command/count including two replay-priority tests; no false green for unrun suites.
- Source video SHA, match JSON provenance and (if any) events JSON provenance.
- `preflight_summary.json`, each `broadcast_timeline_review.json`, clip paths + hashes, a small reviewable first-live/replay/UNKNOWN table.
- For each new PTS: whether first broadcast is VERIFIED by independent continuous timeline review, which prior frames or clips were checked, and any unresolved evidence.
- Exact proposed paid execution command, forecast call count/cost, hard maximum, and rollback behavior. DO NOT RUN paid tests.
- Any blocker: report precise cause and next fix. Do not start Phase9 or modify V1/V2.

## Current acceptance ledger

PASS: offline feedback loop, fixed-EDL A/B feedback decision, first-live-vs-frame-binding separation and replay-priority code fix (pending server regression). PENDING: actual first-broadcast positive certification, unmocked multi-round video experiment, narrative-quality improvement, unseen-match generalization. No formal release until verified.