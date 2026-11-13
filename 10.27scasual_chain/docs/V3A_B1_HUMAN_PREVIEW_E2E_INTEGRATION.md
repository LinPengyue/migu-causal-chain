# V3-A B1 human-attested Goal preview — integration protocol

## Scope (NOT autonomous / NOT release)

Reuses existing `run_story_e2e` flow: Critic diagnosis → goal-review check
→ **human-attested preview fallback** → existing source-chronology insertion
→ candidate duplicate audit → source-PTS gate → standard Phase5 renderer →
standard Verifier and Phase8 record. No new Reasoner, no paid API.

The fallback is invoked ONLY when the ordinary Planner and strict goal repair
did not change the EDL. It requires a matching active goal-coverage issue,
an existing explicit HUMAN first-live attestation bound to original MP4 SHA,
and a user-selected **proposed** in/out window containing the shot/net anchors.
It is disabled for fresh-run, paid, fixtures, exploratory mode, or multi-round.

The proposed window is NOT certified as replay-free or human-approved. Its row
is marked `HUMAN_ATTESTED_PREVIEW_ONLY`, `agent_auto_verified=false`,
`validated_evidence=null`, `cut_boundaries_human_verified=false`.
Verifier and Phase8 MUST NOT accept/promote it: `candidate_accepted=false`,
`transition.promote=false`, `next_action=STOP_NO_ACTION`.
A video render is a review artifact only, never release or BEST.

Strict `FIRST_LIVE_VERIFIED` validation for autonomous repair is unchanged.

## Execute B on server (one new directory; no overwrite)

Run under the usual algo PYTHONPATH / repository worktree. Substitute actual
server paths as needed. **Do not reuse the old output directory**.

```bash
python -m story_video_agent_v3.b1_human_assisted_e2e \
  --match-json /tmp/lpy1_v3a_blind_repair_B_historical_20261112/agent_input/events.json \
  --events-json /tmp/lpy1_v3a_blind_repair_B_historical_20261112/agent_input/events.json \
  --source-mp4 '/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4' \
  --baseline-edl /tmp/lpy1_v3a_blind_repair_B_historical_20261112/agent_input/04_phase5/candidate_edl.json \
  --story-plan /tmp/lpy1_v3a_blind_repair_B_historical_20261112/agent_input/04_phase5/story_plan.json \
  --initial-story-mp4 /tmp/lpy1_v3a_blind_repair_B_historical_20261112/agent_input/04_phase5/story_clean.mp4 \
  --human-first-live-attestation docs/V3A_EXPB_HUMAN_FIRST_LIVE_ATTESTATION.json \
  --preview-media-in 6441.88 --preview-media-out 6459.60 \
  --out-dir /tmp/lpy1_v3a_b1_human_preview_e2e_new
```

Candidate in/out above are **existing experiment hypotheses**, not ground-truth
cut boundaries. They must be reviewed against the original continuous source,
including buildup, shot/net, immediate celebration, replay, and story junction.

## Run and evidence to commit

```bash
pytest -q tests/test_v3a_human_goal_preview.py tests/test_v3a_b1_human_assisted_e2e.py
```

Before accepting the run, inspect: matching source MP4 SHA; original B
baseline row count 8; detected issue; `human_assisted_preview_decision.json`;
candidate EDL row count 9; `edl_diff.json`; `edl_pts_safety.json`;
`candidate_duplicate_audit.json`; rendered MP4 (and ffprobe);
`verifier_report.json`; `phase8_transition.json`; actual BEST fingerprint.
If one condition fails, record exact blocker. Do not fabricate successful video.

A: same procedure only with a separate authentic matching attestation and
confirmed defect. C: complete no-defect baseline must not add goal, even if
a mismatching B attestation is supplied; negative-control test required.

## Responsibility

Cursor runs server unit/integration tests, renders video, preserves history,
and pushes output JSON/report in the same iteration. Human judges the final
clip boundaries and visual narrative. The preview DOES NOT prove the Agent
autonomously judged first broadcast, repaired a story, or improved quality.
