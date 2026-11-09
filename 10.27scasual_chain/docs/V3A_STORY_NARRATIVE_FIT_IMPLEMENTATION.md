# V3-A: story-quality-aware Search / Planner — implementation audit

Base: `e3044abaf1e8360861485bb9415648109ae75343` (previous 78-pass audit HEAD). Development branch: `story-va-v3a-full-chain-audit-fixes`.

## Confirmed problem and design

The failed 3504s bridge illustrates that authentic first-broadcast video and an apparently interesting event do not imply value in the story. The older Search ranked event heat + gap balancing and the Planner could choose FIRST_LIVE-verified clips for a confirmed transition without evaluating their relation to BEFORE and AFTER. It could insert duration rather than missing narrative information. A large source-time gap is normal highlight editing, not itself a semantic defect.

This patch does not encode any match-specific PTS, 3504/2273/6400 winner, football team, or prescribed story answer.

## Changes to real production path

1. **Global Critic:** `large_source_jump` is an informational observation (`temporal_discontinuity_only`, `needs_video_verify`), not an implicit demand for filler. To confirm a jump as a narrative defect, actual VLM semantic evidence must specify `missing_story_information` and `why_transition_breaks` with observed concrete content. Without it, Planner can KEEP the baseline.
2. **Search:** no more gap-balance/time-proximity reward as a narrative-quality proxy. Search attaches exact before/candidate/after source PTS and story roles; independently checks first-LIVE and a source-bound narrative-fit triplet. Bound REJECT reviews remove unsuitable footage from the active shortlist; bound SUPPORT reviews rank first. Unknown fits remain review proposals, not automatic story insertions in production.
3. **Narrative-fit validator:** `story_narrative_fit.py` requires same source SHA256, precise candidate PTS, matching story issue, exact preceding and following segment IDs/PTS, and actual hashed source frame files covering all three contexts. Reviews distinguish `REVIEW_SUPPORTED`, `REVIEW_REJECTED`, `NEEDS_VIDEO_REVIEW`. A bare claim, status string, or event type cannot certify story value. `REVIEW_SUPPORTED` is a *hypothesis*, NOT proven gain.
4. **Autonomous contextual VLM review (future explicitly authorized runs only):** `story_narrative_fit_vlm.py` samples six source frames (two per BEFORE/CANDIDATE/AFTER) using decoder-reported PTS. A real, capped VLM receives ordered frames, a diagnosis, source context and a request to compare the candidate against leaving the baseline unchanged. It must cite actual sent frame IDs spanning all three roles and explain new information and falsifiable gain. If PTS/bindings/citations fail, it cannot support insertion. The main chain reviews at most two candidates per round and reserves two HTTP attempts for Planner and Verifier. **This code path has NOT been executed with a real model or billed in this patch.**
5. **Planner + post-LLM gate:** production `plan_from_diagnosis(require_narrative_fit=True)` requires BOTH a confirmed story defect and an independently validated positive triplet to propose `search_add`. `enforce_narrative_fit_on_plan` rechecks exact source PTS and adjacent anchors AFTER any LLM override, for `search_add` and `replace` (even if replace relies on observation fallback). Unsupported edits become `mark_unresolved`; a coherent unconfirmed gap can be KEEP. Editing existing footage via other actions still follows existing gates.
6. **CLI/observability:** optional `--narrative-fit-evidence-dir` takes an independent `narrative_fit_store.json` or file. `02_round_XX/narrative_fit_review_queue.json` records candidate source/anchor triples. Where real API is explicitly authorized, `narrative_fit_vlm_summary.json` and per-candidate `narrative_fit_review.json` record bounded source-frame review.
7. **Tests:** `tests/test_v3a_phase8_narrative_fit.py` covers valid synthetic video-triplet support, initial safety without fit, negative semantic review, source context frame hash tamper, wrong story anchor, large time jump KEEP, confirmed omitted game state, model-generated unbound search/replace bypass, and six-frame real-VLM-wrapper test with a fake in-memory provider (zero HTTP).

## Protocol and proof limitations

- Independent first-broadcast review remains mandatory; narrative-fit proof DOES NOT substitute for first-live/replay safety.
- All generated reviews are model/human judgments; even a positively cited triplet is NOT a measured improvement to the 95s finished film. The existing candidate render, dual-video Verifier, and user final review determine acceptability. No claim that sparse frames capture all motion or audio.
- SHA checks bind evidence bytes and declared source/PTS metadata. They do not, by themselves, prove a frame was independently re-decoded from the source MP4; extraction manifests and actual decoded PTS are retained, and formal video provenance still uses existing source video and first-live audit.
- Offline production runs with no reviewed triplet may stop with KEEP/UNRESOLVED and preserve V3-R. This is a deliberate refusal to pad highlights to fix source-time gaps.
- Historical Phase8 *offline fixture* tests can still exercise the old EDL control flow; no real paid/production run is allowed to bypass the new narrative gate just because fixtures are present.
- No changes to V1/V2, no paid model calls, no new server experiments, and no claim of test pass in this development turn.

## Required zero-payment server tests before merge

```bash
cd /data2/lpy1/worktrees/migu-v3a-narrative-fit-verify/10.27scasual_chain
# Isolated worktree on updated branch HEAD; do not overwrite the original
# e3044ab 78-pass verification snapshot.
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_*.py -q
```

### Server verification (`d091178` + gap-balance test align)

Worktree: `/data2/lpy1/worktrees/migu-v3a-narrative-fit-verify`  
Report: `/data2/lpy1/_story_va_outputs/v3/plan2/phase8_narrative_fit_verify_d091178.json`

| Suite | Result |
|-------|--------|
| `compileall algo/story_video_agent_v3` | exit 0 |
| `tests/test_v3a_phase8_narrative_fit.py` | **12 passed / 0 failed / 0 skipped** |
| First full `tests/test_v3a_phase8_*.py` on `d091178` | **89 passed / 1 failed** — legacy `test_gap_balance_prefers_not_end_proximity_only` still expected mid-gap to outrank heat after `6f6a62e` removed gap-balance from `rank_score` |
| After aligning that test to diagnostic-only ranking | **90 passed / 0 failed / 0 skipped** (`test_gap_balance_is_diagnostic_not_rank_reward`) |

No paid VLM in this verification. Do not merge main until a story-quality A/B on real video is reviewed.

## Research-quality next gate

Compare the accepted version against untouched V3-R with at least one *unseen match* and more than one story template. Quantify whether specific missing information was restored (not only clip duration), whether adjacent beat coherence improves, whether protected goals and first-live integrity hold, and whether the edit causes redundancy/tempo regression. Only human/story-video evidence can authorize quality claims.
