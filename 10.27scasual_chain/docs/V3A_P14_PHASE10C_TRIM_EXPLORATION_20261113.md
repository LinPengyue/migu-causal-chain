# P14 story quality: reject the overly strong exploratory gate, keep release gate

Source evidence: `docs/V3A_P14_STORY_QUALITY_TRIAL1_SERVER_REPORT_20261113.md`
(`6a1b0dd`). P14 contains three goal actions in a 9-segment, ~94.877s cut.

## Decision (code-level)

The report is correct to **reject** two heuristics: the 12'→47' jump
is coherent, and a short explicit wrap is not objectively missing an
ending. It is **overly strict** to require both a *confirmed* defect
and a *new first-LIVE source candidate* before **any experimental edit**:
the third issue (47'→75' montage causality) can be probed by *removing
existing misleading footage*, which introduces **no new source video**.

The existing `story_exploratory_cut.py` (Phase10-C, already wired in
`story_e2e_agent.py`) implements exactly the necessary separation:
a one-edit, existing-footage `trim/drop/reorder` sandbox is allowed
when story-fit is hypothetical, but it never claims quality improvement,
autonomous model selection, first-LIVE validation, or formal release.
The strict `Planner→Executor→Verifier` production logic stays intact.

## One pre-registered, reversible experiment

Question: does trimming the **last 25% of the single buildup clip
immediately preceding the equalizer** improve narrative coherence
relative to baseline (i.e., remove a misleading 47' whistle-like tail
that seems to cause a much later equalizer) without losing necessary
pressure/setup?

The shell driver `docs/run_v3a_p14_phase10c_trim_trial1_20261113.sh`
does **not hardcode media PTS or goal candidates**. It reads the exact
P14 EDL and existing Critic transition issue; confirms three goal
segments, adjacent buildup→equalizer, and the original source SHA; then
produces a **fixture-sourced** proposal to shorten only that existing
non-protected clip. Phase10-C rejects any proposal that changes a goal
window, any protected anchor, PTS order or introduces replay/slow-motion.

**This is a developer-authored hypothesis / offline fixture. It does
not establish autonomous Agent defect finding or edit selection.**

Run on an isolated checkout, no fee:

```bash
git fetch origin
git switch story-va-v3a-p14-story-quality-20261113
git pull --ff-only
cd 10.27scasual_chain
bash docs/run_v3a_p14_phase10c_trim_trial1_20261113.sh
```

Normal formal delivery can remain `BLOCKED`, even if Phase10-C
successfully renders an X/Y blind comparison. The driver checks
**Phase10-C's independent status** rather than treating the formal CLI
exit code as the experiment outcome.

Expected experimental files:

- `/tmp/lpy1_v3a_p14_phase10_c_trim_trial1_20261113/trial1_result.json`
- `.../agent/02_round_01/phase10_exploratory/blind_review/X.mp4`
- `.../agent/02_round_01/phase10_exploratory/blind_review/Y.mp4`
- `.../agent/02_round_01/phase10_exploratory/exploratory_trial.json`
- **private allocation** `PRIVATE_unblinding.json` outside the blind folder.

The user should **watch X/Y first**, choosing which gives the clearer
opening→buildup→equalizer progression. Assess story completeness,
causal clarity, emotional pacing, visual continuity and audio. **Never
reveal the private allocation before judgment**. A shorter cut is not
automatically better.

### Release / safety unchanged

All original three goal action windows and protected scoreboard/title
segments remain byte-identical in the candidate EDL. The source content
is a **subset of existing P14**; the exploratory path does not certify
those inherited clips as FIRST_LIVE_VERIFIED. It cannot release, update
BEST, or claim first-live/quality improvement. If preview has replay or
slow motion, it must not become a deliverable.

If the blind test shows no material improvement, reject the trim.
Avoid continuing blind insertions from unverified EVENT_PTS candidates.
If the user wants true autonomous repair next, investigate an authorized
REAL_VLM story-semantic critique/proposal on a *separate* budget-controlled
run; do not mislabel fixture output as agent self-correction.
