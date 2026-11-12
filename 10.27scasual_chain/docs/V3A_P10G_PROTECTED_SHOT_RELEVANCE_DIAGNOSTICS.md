# P10-G: protected-shot relevance diagnostics for the *whole* story pipeline

Status: CODE COMMITTED; **SERVER TESTS AND VIDEO VALIDATION PENDING**. No
paid HTTP. No changes to V1/V2/V3-R and no production release authorization.

## Why

A human preferred the longer P10-F B fullcut (Y) for its pre-goal buildup, but
reported short apparently unrelated visual events near X 00:38 and 01:03.
This is qualitative development feedback, **not** a sealed
NECESSARY/REDUNDANT determination or direct source-frame verification.
Do **not** open P10-F sealed risk outputs before the independent label is locked.

The published B strict_lin inventory has one editable 12-second buildup.
All goal-action and scoreboard rows are marked protected from exploratory
deletion. Thus testing only the buildup cannot certify fullcut relevance.

From the *published EDL durations* (default placeholder 2.5s), the shorter
cut estimates story duration **91s**, vs X MP4 **92.904s**. The ~1.904s
difference creates timing ambiguity. Around X 00:38, candidates are
**deficit_scoreboard_anchor / equalizer_goal_action**; around X 01:03,
**equalizer_scoreboard_anchor / go_ahead_goal_action**. These are only
candidate intervals, not verified source-frame identities.

## Code changes

- `story_timeline.story_time_to_media`: contiguous [start, end) interval
  ownership; exactly-on-seam time maps to the next segment (last end inclusive).
- `story_cut_relevance_audit`: inventory of all active source-bound rows,
  **including protected** windows. Protection is not narrative relevance.
  Optional human timestamp audit expands time uncertainty by MP4/EDL duration
  discrepancy. No video interpretation, EDL change, or auto-trim.
- `story_e2e_agent.run_story_e2e`: emits
  `00_baseline/cut_relevance_inventory.json` in the unified main pipeline.
- `tests/test_v3a_p10g_cut_relevance_audit.py`: boundary, conservative
  ambiguity, all-segment coverage, CLI, invalid timestamps, and immutable EDL.

## Cursor engineering verification (zero paid)

In a new server worktree from `story-va-v3a-p10g-cut-relevance-audit`:

```bash
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest -q tests/test_v3a_p10g_cut_relevance_audit.py
PYTHONPATH=algo python -m pytest -q tests/test_v3a_phase10_*.py tests/test_v3a_phase10d_*.py tests/test_v3a_phase10e_*.py tests/test_v3a_phase10f_*.py
PYTHONPATH=algo python -m pytest -q tests/test_v3a_phase8_*.py
```

Run the read-only offline audit against the **shorter candidate EDL** for
the X playback observations, *without opening the X/Y mapping key or sealed
risk predictions*. Locate the actual short candidate EDL from the existing
P10-F exploratory run; don't invent a path:

```bash
PYTHONPATH=algo python -m story_video_agent_v3.story_cut_relevance_audit \
  --edl "$P10F_SHORT_CANDIDATE_EDL" \
  --time 38 --time 63 \
  --rendered-duration-sec 92.904 \
  --out "$P10G_OUT/X_38_63_source_candidates.json"
```

Also verify the longer baseline EDL and fullcut, but DO NOT compare model
risk to human labels until the blind label is independently finalized.
The temporary human observation times are for **offline QA**, not Agent
inference, benchmark labels, or hardcoded runtime rules.

## Required server evidence

1. Attach source file hash, original EDL JSON and *exact* MP4 duration,
   plus the report's candidate segment IDs/source PTS for both observations.
2. Review source MP4 and rendered seam footage on both sides of each time
   interval. Establish if the interruption is within a protected goal window,
   a cut-boundary artifact, or a separate scoreboard/overlay.
3. Verify approach/shot/net/scoreboard and FIRST_LIVE evidence independently;
   a 22s goal window is not automatically narratively perfect.
4. Only after evidence identifies an actual irrelevant region should the
   algorithm propose **bounded visual-evidence-supported** trim/drop.
   Never remove a whole protected goal action solely due to an event label.
5. Keep `closed_loop` B's pre-existing non-monotonic PTS case BLOCKED.
   Do not sort footage or silently delete the conflicting atom-fill shot.
6. Report tests, exact commit and artifacts; no paid API and no quality
   improvement claim until whole-video validation.

## Research implications

Separate three predicates: (i) broadcast/first-live safety,
(ii) event evidence completeness, (iii) global narrative contribution.
Neither (i) nor (ii) implies (iii). This distinction must hold across
matches and story templates. It is an engineering/research hypothesis,
not yet evidence that a new algorithm works or a finished ACL method.
