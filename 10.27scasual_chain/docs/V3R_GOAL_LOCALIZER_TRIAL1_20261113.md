# V3-R raw-only goal localization: bounded trial 1/2

## Purpose and baseline

Preserve the good P14 V3-R story-planning path. This is a **diagnostic
trial of the already implemented P3/P13 first-live localizer**, not a new
agent, automatic timestamp insertion, or a paid experiment.

- Frozen input: original UAE–Oman MP4 SHA `a66147f79609c8fbf831a8bd29de4c6d7f746b314b2b18a88ffb1fc5f319da9c`; raw events SHA `ddae99b21cbfcd1c75ddf620d957578e57c2c013d607ac893655c4d52b7e779e`.
- Frozen raw-only result: `/tmp/lpy1_v3a_cv_raw_e2e_20261113_first_run`, source `402dbb81`, V3-R 8 segments, equalizer missing.
- Frozen development fallback: P14 `baa8d59`, `HUMAN_ATOM_ENRICHED_DEV`, 3 goal-action segments, ~94.877s. **Do not delete or overwrite it.** This is *not* raw-only benchmark evidence.
- No API requests, no `*_causal.json`, no `strip_gold.json`, no hardcoded 6448s in inputs, no BEST changes.

## Run existing code only (first)

On server in a **clean checkout** of `story-va-v3r-goal-localizer-trial1-20261113`:

```bash
cd 10.27scasual_chain
set -euo pipefail
ROOT=/tmp/lpy1_v3a_cv_raw_e2e_20261113_first_run
REC="$ROOT/01_to_04_fresh_v3r/03_v1_adapt/goal_recovery.json"
MP4="/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4"
EVENTS="data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json"
OUT=/tmp/lpy1_v3r_goal_localizer_trial1_20261113
test -s "$REC"
test -s "$MP4"
test -s "$EVENTS"
test ! -e "$OUT"
python - <<'PY'
import json
from pathlib import Path
p=Path("/tmp/lpy1_v3a_cv_raw_e2e_20261113_first_run/01_to_04_fresh_v3r/03_v1_adapt/goal_recovery.json")
x=json.loads(p.read_text())
a=[c for c in x["candidates"] if c.get("candidate_id")=="goalcand_03_01_to_11"]
assert len(a)==1 and a[0].get("goal_action_sec") is None, a
print("PRECHECK:", a[0]["candidate_id"], a[0].get("possible_action_interval"))
PY
PYTHONPATH=.:algo python -m story_video_agent_v3.first_live_localize \
  --source-mp4 "$MP4" --events-json "$EVENTS" \
  --goal-recovery "$REC" --out-dir "$OUT" \
  --candidate-id goalcand_03_01_to_11 \
  --max-candidates 4 --max-video-read-sec 90 \
  --expected-source-sha256 a66147f79609c8fbf831a8bd29de4c6d7f746b314b2b18a88ffb1fc5f319da9c \
  --expected-events-sha256 ddae99b21cbfcd1c75ddf620d957578e57c2c013d607ac893655c4d52b7e779e \
  > /tmp/lpy1_v3r_goal_localizer_trial1_stdout.txt 2>&1
```

**Do not enable skip-OCR unless the OCR dependency genuinely fails; report
the reason and rerun in a separate fresh output directory.** No modifying
the recovery JSON or rewriting timestamps. The script does not auto-fill
`goal_action_sec` by design.

## Audit actual output and source code

Inspect `$OUT/raw_only_video_localization_summary.json`,
`$OUT/goalcand_03_01_to_11/candidate_audits.json`,
`$OUT/goalcand_03_01_to_11/evidence_pack.json`, and the actual continuous
source clips / cited frame paths. Record:

1. Number of proposed candidates, decoded clips and actual video PTS;
2. Whether the original goal action is **visibly in the candidate set**;
3. Whether shot/net are both visible in one continuous original broadcast
   clip; whether replay or slow motion is possible;
4. Whether the localizer failed due to candidate recall, OCR/score bracket,
   frame coverage, semantics, or strict first-live verification;
5. Which **existing** adapter/callsite would consume a verified
   observation, and exactly what evidence is still missing. Never
   equate score confirmation or absence of pHash match with first-live.
6. No regression to P14 and no changes to Planner, EDL Editor, V3-A Loop.

Do not claim goal recovered if this run merely proposes a video window.
If the visual clip includes a candidate but lacks semantic proof, report
`CANDIDATE_FOUND_UNVERIFIED`, not PASS.

## Trial-1 decision

- Candidate search **misses the action**: locate the general cause of
  missed coverage. Allow **at most one minimal cross-match-safe change**
  in a second trial, with tests and a heldout match. Do not specialize
  timestamps or score strings.
- Candidate found, but no independent first-live evidence: stop automatic
  insertion and identify the evidence gap; no new gates or modules.
- Candidate and verifiable source evidence: wire to the **existing**
  Goal Recovery evidence interface only, without modifying V3-R
  narrative planning; re-run raw-only full E2E in a fresh output.
- No substantive progress by trial 2, or story regression: **stop raw-only
  exploration and return to P14 atomic-enriched development track**.

Deliver a concise report with source SHA, code SHA, exact command,
output directory, clip/PTS evidence, stage-specific verdict, and whether
trial 2 is warranted. This is not an authorization for paid VLM.
