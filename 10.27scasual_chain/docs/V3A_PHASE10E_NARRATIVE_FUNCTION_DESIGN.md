# P10-E: narrative-function preservation after P10-D blind feedback

Status: **ZERO-PAID SERVER REGRESSION GREEN ON `d054b96`**; CROSS-VIDEO /
NEGATIVE-CONTROL VALIDATION STILL PENDING. See
`docs/V3A_PHASE10E_SERVER_VERIFY_d054b96.json`. No paid HTTP; story-quality
gain remains UNVERIFIED; V3-R remains BEST.

## Human feedback (evaluation-only; never runtime Agent input)

P10-D A UAE–Oman, one human reviewer: X slightly preferred to Y.
The reviewer identified X 00:31–00:40 as important pursuit/effort buildup
before the comeback. The shorter candidate lost narrative motivation.
This is one development observation, not G2 three-rater consensus.
Do NOT use the X/Y identity mapping, segment ID, feedback labels, or
this match as model inference inputs or hardcoded rules.

## Mechanism

P10-D Planner correctly kept the formal story but hypothesized that
removing a non-goal buildup would tighten pacing. The earlier prompt
explicitly favored dropping a buildup/bridge, biasing the search.
P10-E removes that bias and asks Planner to account for motivation,
effort, anticipation, and what the neighboring clips cannot convey.
This is an LLM prompt adjustment, not evidence of learned semantics.

New `story_narrative_function.py` audits the editorial sequence
around any proposed drop/trim/reorder. It flags potentially lost
motivation/effort bridges using generic EDL role hints and neighbors.
It does NOT classify video content, declare a defect, or block a
legitimate blind exploratory candidate. Risk is always UNVERIFIED;
full before/target/after footage and whole-video human comparison are
still necessary.

The audit is attached to `propose_exploratory_cut` results as
`narrative_function_loss`. P10-D provenance, safety gates, and BEST
semantics remain unchanged.

## Cursor zero-paid regression

Use a new independent worktree on `story-va-v3a-phase10e-narrative-function`.
Do not modify algorithm code or use paid APIs.

```bash
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest tests/test_v3a_phase10_*.py tests/test_v3a_phase10d_*.py tests/test_v3a_phase10e_*.py -q
PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_*.py -q
```

Re-run the P10-D A offline fixture ONLY as a structural regression
(0 HTTP). Assert the proposed drop remains safely renderable but
its audit is marked `HIGH_UNVERIFIED` when EDL role hints place it
between setup and turn; inspect actual role hints rather than
manufacturing expected result. Preserve original baseline hashes,
goals, PTS, first-live checks and anonymous fullcut X/Y.

### Server verification (`d054b96`)

Worktree: `/data2/lpy1/worktrees/migu-v3a-phase10e-verify`

| Check | Result |
|-------|--------|
| compileall | exit 0 |
| `test_v3a_phase10_*.py` + d + e | **68 passed** |
| `test_v3a_phase8_*.py` | **129 passed** |
| Paid HTTP | **0** |
| A offline fixture drop | still `EXPLORATORY_RENDERED_NOT_VERIFIED` / `BLIND_PAIR_READY` |
| `narrative_function_loss.risk_level` | **`HIGH_UNVERIFIED`** |
| Actual role context | `deficit_scoreboard_anchor` → `buildup_action` → `equalizer_goal_action` |
| Signals | `potential_motivation_or_effort_visual_removed`, `setup_to_turn_bridge_may_be_lost` |
| Goals / baseline hashes / fullcut align | preserved / unchanged / aligned |

This does **not** validate that the heuristic improves story quality or
correctly spares redundant clips on held-out matches.

## Next research gate

Before any additional paid call, evaluate this structural heuristic on
at least one held-out match/other story pattern and include negative
controls where removing a truly redundant clip does not lose the
motivational bridge. The current heuristic must not be called
validated until video-grounded blind ratings support it. A/B test
the old vs new Planner instructions at matched model, budget, and
observations to separate prompt bias from graph contribution.
