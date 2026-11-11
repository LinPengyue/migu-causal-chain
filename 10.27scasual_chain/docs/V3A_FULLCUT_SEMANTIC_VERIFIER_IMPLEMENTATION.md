# V3-A Phase8: baseline-versus-candidate full-cut semantic screening

## Goal, source and scope

Starting from the existing dual-video Verifier, fill the gap between **candidate clip suitability** and **actual completed story quality** without changing V1/V2 or encoding any match-specific IDs. The prior offline B/C full-cut comparisons showed that new interesting footage can slow a complete story without explaining a missing narrative state. This design checks *incremental story gain*, not footage heat or duration by itself.

**Implementation status:** committed source + synthetic tests; no server regression or real paid VLM verification has been performed on this HEAD. The existing 90-pass result pertains to the earlier `e258a23` version only.

## Code path

- `story_fullcut_sampling.py::fullcut_edit_context_sample_plan`: allocates the existing **four paired slots/eight frames** to `pre_edit`, `edit_impact`, `post_edit` and a later `global_ending` when available. The edit's baseline counterpart for an inserted scene is explicitly labeled an **unedited cut boundary**, not the same source action. Newly added segments have priority over incidental metadata changes; missing slots are disclosed.
- `dual_video_vision_verifier.py`: reuses its already-authorized **single** dual-video vision call (no extra HTTP) but asks for a concise structured `fullcut_comparison` over information gain, beat continuity, pacing tradeoff, redundancy and global regression. Prompts include measured EDL duration difference; no source-time-gap or elapsed-time reward.
- `story_fullcut_semantic.py::screen_fullcut_semantic_gain`: independently binds both output MP4 SHA256s and extracted sample-frame bytes, checks that every dimension cites real frames from **both versions**, and requires coverage at the edit, before, after and final narrative context. Truncated, hallucinated, unpaired or missing citations return `UNVERIFIED`. `SCREENED_NO_GAIN` is an advisory rejection of the current cut. `SCREENED_BETTER` is **PROMISING, not formal IMPROVED**.
- `story_fullcut_semantic.py::constrain_sampled_verifier_payload`: strips model-supplied `accept_candidate`, `IMPROVED` and claims of no global regression. A sparse-frame screen cannot establish finished-story pacing/audio or unseen beat regression.
- `story_e2e_agent.py`: writes `fullcut_semantic_screen.json` and attaches status to `fullcut_delta_report.json`; the Phase8 production verdict carries `require_fullcut_semantic_gate=True` for real VLM observations and `fullcut_gate_promote=False` for sparse still observations.
- `story_loop_policy.py`: independent promotion guard. Even a forged `REAL_VLM, BETTER, SUFFICIENT` with valid safety and compared-best flags cannot `PROMOTE_BEST` when its explicit full-cut gate is false. Existing legacy/fixture behavior is maintained unless gate is explicitly requested.

## Honest limitations

This is a **sampled comparison of two complete rendered films** (edit context plus a distant end-of-story beat), not an inspection of every frame or full audio. It cannot guarantee that the story improved. It can identify candidate issues worth pursuing, and it can prevent unverified model confidence from becoming formal `BEST` or `RELEASE_READY`. Even an apparently positive result needs stronger evidence (complete video/audio review, independent human review, or later native full-video model with checkable source bindings) before promotion.

The current implementation deliberately never sets `fullcut_gate_promote=True`; do **not** relax that merely to make tests or an experimental run appear successful. Authorized real VLM evaluation uses the existing API-budget gates only; this patch did not authorize or invoke a paid call.

## Zero-payment validation before any release

On a NEW isolated worktree with the latest branch HEAD, run:

```bash
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_fullcut_*.py -q
PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_*.py -q
# Optional broader regression:
PYTHONPATH=algo python -m pytest tests/test_v3a_phase6*.py -q
```

The new tests are pure, use synthetic files and have **zero HTTP**. Record actual pass/fail/skipped counts, tracebacks, and HEAD. Do not claim the new suite has passed until the server reports its result.

## End-to-end quality gate after code regression

Once real evaluation is explicitly approved, inspect the fully rendered untouched baseline and candidate with matched issue context. Keep the untouched V3-R as default. Neither first-live certification nor a positive triplet/contextual screen alone establishes end-to-end story improvement. Report changes to viewer comprehension, redundant scenes, pacing and late-story payoff; test across other matches and story templates before treating generalization as proven.
