# Scheme-A Stage1 fix + Run02 original-context acceptance (2026-11-15)

HEAD: `be97ad01fef2bad1897714374c12d0e331273a9a`  
Branch: `story-va-e2e-v2-story-first-20261114`  
Server out: `/tmp/lpy1_scheme_a_stage1_run02_origctx_20261115/`  
Zero HTTP. Historical Run02 untouched.

## Pytest

Story-First / Scheme-A / evidence-adapter suite:

```text
47 passed in 0.31s
```

Log: `docs/ARTIFACT_scheme_a_stage1_fix_pytest_core_20261115.txt`

(Patch already on remote as `be97ad0`; local FF from `31d385a`.)

## Run02 original input SHA

All three Run02 audit paths match on disk (`sha_check=PASS`):

- events `33958b10…`
- EDL `b38434b9…`
- plan `ba64c215…`

## Rebuild + score request

1. Rebuilt `prepared_story_input` with same P14 files, `--max-hypotheses 2` → scope identical to Run02 anchors `[1347.123, 6436.924]`.
2. Offline schema recovery from Run02 `llm_raw_response.txt` → H1+H2 structurally accepted.
3. `story_first_a_ranker` prepared-only → `http_attempts=0`, status `PREPARED_ONLY_ZERO_HTTP`.

Artifacts:

- `…/scheme_a_ranking/score_model_input.json`
- `…/scheme_a_ranking/scheme_a_audit.json`
- also copied under `docs/ARTIFACT_scheme_a_run02_origctx_*`

## score_model_input checks

| Check | Result |
|------|--------|
| `frozen_story_plan` | **dict**, full keys (segments/candidate_edl/narration/…) |
| `current_edl` | **9** rows; timed media_in **monotonic** (title open/close have null media_in) |
| event_context | **8** cited events |
| annotation_notes | all 8 present (team/player notes) |
| H1 `event_000622` | `known_replay_or_slowmo=true` |
| http_attempts | **0** |

### EDL playback (timed)

1. opening goal 1325.123 → 2. deficit 1409.43 → 3. buildup 4706.45 → 4. equalizer action 6436.924 → 5. equalizer board 6534.62 → 6. go-ahead 6829.456 → 7. go-ahead board 6956.12

### Notes (ranking-relevant)

- H2 support all **2队（阿曼）** notes: subs / GK long pass / aerial win
- H1: foul notes 2队→1队; intercepts **mixed teams** (635=2队截获, 636=1队截获); VAR replay marked

## Gates

`acceptance_all_pass=true` in `origctx_acceptance_report.json`.  
No paid scoring started.
