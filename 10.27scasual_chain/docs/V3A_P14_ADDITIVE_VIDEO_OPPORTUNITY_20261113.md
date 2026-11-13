# V3-A P14 additive story opportunity — original-video source search (Trial A)

## Why this is not another delete/trim ablation

The 9-cut / ~94.877s P14 story already retains opening, equalizer and
go-ahead goals. Deleting the only buildup segment will likely remove story
information rather than create it. The previous exploratory trim is abandoned.

The frozen trial report `V3A_P14_STORY_QUALITY_TRIAL1_SERVER_REPORT_20261113.md`
found only one worthwhile ambiguity: in the finished montage, a buildup
shot apparently at ~47' directly precedes the ~75' equalizer. This is
**not proven a defect**; it is an opportunity to look for a specific
otherwise missing story state immediately ahead of that goal.

The existing `story_evidence_search._rank_events_in_window` retrieves
scored event candidates over a potentially huge source interval. Highest
event heat and gap balance cannot establish story fit. Real Trial 1
event-PTS candidates remained near ~47', hence failed to test the
actual pre-equalizer context.

## What changed

New: `story_additive_opportunity.py`.

- Pure `discover_additive_opportunities`: examines adjacent EDL roles
  and PTS. Buildup/pressure/setup/development → distant goal action
  creates an *unverified narrative opportunity*, NOT a confirmed defect.
  Other timeline jumps and an already-coherent ending are ignored.
- A 150-second source-PTS lookback before the protected goal window
  is divided into at most **four distinct 12-second video probes**.
  Occupied EDL windows are excluded; no goals are re-localized.
  The windows are selected by **source-video time**, not event heat.
  The prior is video-first, not proof that these clips are appropriate.
- `build_opportunity_video_pack` reads the ORIGINAL source MP4,
  checks SHA-256, exports original sequential 12s clips and one
  up-to-32s finished-story seam including the following goal action; all claims default to
  UNVERIFIED. Maximum original-video clip request is 48s.
- `story_e2e_agent.run_story_e2e`: opt-in at round 1 after actual
  Critic diagnosis; writes separate `additive_opportunities.json`
  and `additive_story_probe.json`. It does not inject EDL changes,
  confirmed issues, Planner intents, Verifier passes or BEST changes.
- Both V3-A CLIs accept `--enable-additive-story-probe`.
  Without flag, existing behavior is unchanged.
- Separately guarded `--enable-additive-native-semantic-review` requires
  `--enable-additive-story-probe`, `--enable-real-api`, and
  `--i-approve-budget`. It uses the shared capped provider for one real
  continuous-video baseline-vs-source comparison. Its verdict is only
  a story-fit prior, not first-LIVE proof or permission to modify EDL.
- `tests/test_v3a_additive_story_opportunity.py`: source lookback,
  occupied-window exclusion, rejection of generic gaps, bounds,
  source SHA, no overwrite, no quality/first-live assertions.

The default video search is zero-paid and not itself a semantic classifier.
An additional native-video semantic review is implemented, but **disabled**
in this experiment; paid calls require separate explicit authorization.
Neither mode automatically adds footage, claims FIRST_LIVE or promotes BEST.

## Run on the private video server

Do not run the abandoned `run_v3a_p14_phase10c_trim_trial1_20261113.sh`.

Use a clean worktree:

```bash
git fetch origin
git switch story-va-v3a-p14-additive-video-opportunity-20261113
git pull --ff-only
cd 10.27scasual_chain

bash docs/run_v3a_p14_additive_video_probe_20261113.sh
```

This runner reuses the actual existing P14 Phase5 files from the
successful `/tmp/lpy1_v3a_p14_cv_integration_20261113/run`,
asserts original MP4+event SHA, executes ten focused unit/mock tests,
runs one current V3-A round with ZERO paid HTTP, confirms frozen P14
MP4/EDL hashes, and checks that the probe exported non-empty clips.

Output:

- `/tmp/lpy1_v3a_p14_additive_probe_20261113/probe_report.json`
- `.../agent/02_round_01/additive_opportunities.json`
- `.../agent/02_round_01/additive_opportunity_video_pack/opportunity_video_manifest.json`
- `.../agent/02_round_01/additive_opportunity_video_pack/01_story_seam.mp4`
- `.../agent/02_round_01/additive_opportunity_video_pack/01_source_probe_01.mp4`
  through `01_source_probe_04.mp4`, if ffmpeg succeeds.

Formal full E2E may exit nonzero/BLOCKED because FIRST_LIVE remains
UNRESOLVED, as before. The script checks the **independent probe**
instead; an export pass is not a release pass.

## Next evidence-driven decision

Evaluate the up-to-32s finished cut seam (which includes the following goal action) and four 12s source clips.
For each candidate, distinguish:

1. Video-observed **new information** that changes understanding of
   the lead-up, vs another generic attack/low-value shot.
2. Baseline already coherent vs a specific misleading implied
   causal continuity needing correction.
3. FIRST_LIVE/REPLAY/UNKNOWN — never infer from event LIVE tag,
   frame similarity or scoreboard timing.
4. Whether video supports insertion exactly between the two protected
   anchors, with source-PTS monotonicity and no duplicate.
5. Whether the final full cut actually improves when rendered and
   compared against the untouched P14 story.

If no candidate explains a new relevant state, the search result
should be `NO_SEMANTIC_GAIN`, not a forced +12-second bridge.
If evidence is indecisive, request an explicitly authorized bounded
semantic VLM review rather than promoting a speculative clip.
No match-specific code, no causal-label use by this new search,
no BEST edits and no official raw-only benchmark claim.
