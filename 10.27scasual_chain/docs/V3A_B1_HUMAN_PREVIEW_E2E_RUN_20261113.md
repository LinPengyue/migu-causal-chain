# V3-A B1 human-attested Goal preview E2E — 2026-11-13

Branch: `story-va-v3a-p17-native-broadcast-observer` @ `f5f2ca6`  
Protocol: `docs/V3A_B1_HUMAN_PREVIEW_E2E_INTEGRATION.md`  
Out (new, no overwrite): `/tmp/lpy1_v3a_b1_human_preview_e2e_20261113/`  
Docs mirror: `docs/b1_human_preview_e2e_20261113/`

## Tests

```text
pytest -q tests/test_v3a_human_goal_preview.py tests/test_v3a_b1_human_assisted_e2e.py
...........                                                          [100%]
11 passed
```

`PYTHONPATH=<repo>/10.27scasual_chain` (imports `algo.story_video_agent_v3.*`). No gate relaxation.

## B — defective historical 8-seg EDL (preview path)

Inputs: B wrong EDL/plan/story + original MP4/events + `docs/V3A_EXPB_HUMAN_FIRST_LIVE_ATTESTATION.json` + proposed window **6441.88–6459.60**.  
**No** incomplete inventory / strict first-live pack as repair evidence.

| Step | Result |
| --- | --- |
| Critic | `goal_coverage_01_to_11` (major) among 4 issues |
| Strict goal repair | unchanged (`NO_EXTERNAL_REVIEW` / UNRESOLVED) |
| `human_assisted_preview_decision` | **HUMAN_ASSISTED_CANDIDATE_PREVIEW**, `changed=true`, `cut_boundaries_human_verified=false`, `requires_human_review_of_entire_candidate_window=true` |
| EDL | **8 → 9**; added `seg_goal_video_repair_goal_coverage_01_to_11` @ 6441.88–6459.6; `HUMAN_ATTESTED_PREVIEW_ONLY`, `validated_evidence=null`, `agent_auto_verified=false` |
| PTS safety | `ok=true` |
| Duplicate audit | `finding_count=0` |
| Render | `ok=true` → `.../02_round_01/candidate_render/story_clean.mp4` (90.558s, ~31.3MB, sha256 `98e9f922…`) |
| Human review bundle | `99_final/human_review_candidate/v3a_candidate.mp4` |
| Verifier | `candidate_accepted=false`, veto `HUMAN_ASSISTED_PREVIEW_NOT_RELEASE_ELIGIBLE`, evidence INSUFFICIENT |
| Phase8 | `next_action=STOP_NO_ACTION`, `promote=false`, reason `human_assisted_preview_requires_video_review_not_best` |
| Delivery | **BLOCKED** / **HUMAN_REVIEW_REQUIRED** (`cut_boundaries_human_verified=false`) |
| Paid HTTP | **0 / $0** |
| BEST | stayed **v0**; no promote; no release |

**REVIEW REQUIRED:** proposed in/out are experiment hypotheses only; not human-approved cut boundaries.

## C — clean no-defect negative control

Same B attestation + window deliberately supplied against C 9-seg clean baseline.

| Check | Result |
| --- | --- |
| Preview | **UNRESOLVED** `no_unique_matching_goal_coverage_issue` |
| EDL | unchanged (9 rows); `edl_diff.changed=false` |
| Render | skipped |
| Phase8 | `STOP_NO_ACTION`, `promote=false` |
| Paid / BEST / release | 0 HTTP; BEST v0; release false |

## A

**Not run.** A needs an independent, match-bound human attestation for its own defect; **must not reuse B’s attestation** as formal proof.

## Historical artifacts

Fingerprints for B historical `agent_run*` / `private_eval` and prior incomplete B1 tree: **unchanged** before→after. New dirs only under `/tmp/lpy1_v3a_b1_human_preview_e2e_20261113/`.

## Key artifact paths (server)

- B preview decision / EDL diff / PTS / dup / render JSON / transition: `docs/b1_human_preview_e2e_20261113/B/`
- B candidate video (not in git): `/tmp/lpy1_v3a_b1_human_preview_e2e_20261113/agent_run_B/02_round_01/candidate_render/story_clean.mp4`
- C negative summaries: `docs/b1_human_preview_e2e_20261113/C/`
- Full logs: `B/b1_B_full_run.txt`, `C/b1_C_negative_full_run.txt`
