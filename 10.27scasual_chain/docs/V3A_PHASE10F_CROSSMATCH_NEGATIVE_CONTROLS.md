# P10-F: held-out match and genuinely redundant segment controls

Status: **ZERO-PAID SERVER REGRESSION GREEN ON `de80ddc`**; B inventories +
one anonymous fullcut pair ready; **HUMAN LABELS STILL PENDING** (do not
unseal risk predictions before labeling). Metrics not computed yet.
V3-R remains BEST. See `docs/V3A_PHASE10F_SERVER_VERIFY_de80ddc.json`.

## Question

Does the generic P10-E role-based narrative-function audit distinguish
necessary motivational footage from genuinely redundant footage across
matches, rather than just recognize a known A-case role pattern?

## Required data and leakage separation

Use B Osasuna–Celta frozen V3-R Phase5 as first cross-match test, plus
additional unseen match when available. A UAE–Oman is a known development
example and cannot count as held-out. Do not feed human ratings, known
A segment ID, benchmark gold, or previous preferred X/Y mappings into
Planner/Critic/Agent runtime.

For each eligible unprotected, first-live segment, record an independent
human assessment of the **fullcut difference** (baseline vs one deletion/
bounded trim), blinded to P10-E risk. Human labels:
- NECESSARY: removal materially harms the story's motivation/continuity
- REDUNDANT: removal does not harm the story, including its buildup
- UNCERTAIN: insufficient evidence, no forced classification

Include at least one **genuine redundant** example, not an artificial
synthetic label. A segment named `buildup` can be redundant; a neutral
role can still be narratively essential. Never treat role strings as
ground-truth video semantics.

## Zero-paid steps for Cursor

1. Create independent worktree from
   `story-va-v3a-phase10f-crossmatch-controls`.
2. Run:
```bash
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest tests/test_v3a_phase10_*.py tests/test_v3a_phase10d_*.py tests/test_v3a_phase10e_*.py tests/test_v3a_phase10f_*.py -q
PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_*.py -q
```
3. Inventory B frozen EDL and identify unprotected source-bound clips.
   Export anonymized candidate manifests with role, source PTS, duration,
   neighboring roles, source hash and safety eligibility.
4. Generate bounded **offline** candidate pairs using existing
   `propose_exploratory_cut` and `execute_exploratory_trial` (fixture
   provenance only). No paid API; no new clips; no replay; no baseline
   changes. For blocked proposals record exact reason; never force render.
5. Collect human whole-video labels **before exposing risk outputs**.
   Keep private X/Y mapping sealed. Record labels in a separate evaluation
   file, never inside Agent runtime or benchmark gold.
6. Join sealed labels with recorded risk outputs by unique case_id, then
   execute:
```bash
PYTHONPATH=algo python -m story_video_agent_v3.story_phase10f_evaluation \
  --cases "$SEALED_CASES_JSON" --out "$P10F_REPORT_DIR/metrics.json"
```
7. Report necessary-recall, redundant false-alarm rate, abstentions,
   confusion matrix and per-match distribution. At least two matches
   plus both label classes required even for descriptive evidence.
   Do not call it generalization proof. Upload small JSON and logs only.

### Server verification (`de80ddc`) — steps 1–4 done; 5–7 await human

| Check | Result |
|-------|--------|
| compileall | exit 0 |
| phase10(+d/e/f) | **71 passed** |
| phase8 | **129 passed** |
| Paid HTTP | **0** |
| B closed_loop inventory | 2 unprotected media; **0 eligible** — `baseline_source_pts_not_monotonic` (atom_fill buildup vs equalizer). No force-render. |
| B strict_lin inventory | 1 unprotected media; **1 eligible** — offline pair rendered |
| Human blind pack | `_story_va_outputs/v3/plan2/phase10f_blind_xy_download/{X,Y}.mp4` |
| Risk predictions | sealed under `docs/phase10f_preview/SEALED_RISK_PREDICTIONS.json` — open only after labels |
| Metrics | **NOT RUN** (`AWAITING_HUMAN_LABELS`) |

## Decision

If redundant false alarms are high, P10-E is over-protective and should
move from role heuristics to contextual visual function comparison. If
necessary footage is missed, expand contextual observation rather than
add match-specific keywords. No new paid experiment authorized by this
protocol. V3-R remains BEST until G0/G1/G2 evidence.
