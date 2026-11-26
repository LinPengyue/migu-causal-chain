# R4/R5.1 — adapt R3 to original Story Agent, not a new agent

User decision: keep original P1/P2/P3, inner/outer loop and Verifier exactly
as implemented. Outer rounds progressively add causally/narratively related
story footage; P3 optimizes each inserted passage. No new per-round quality
veto, no replacement of the original loop, no online Causal-4 score.

Baseline: R3 data 539c421; legacy delivery code 93804fb. The experimental
single-loop general_story_agent.py at cf397a7 is not the selected route.
Do not execute it. This adapter is research-only.

## Implemented
r3_legacy_agent_adapter.py generates a native Story Plan / candidate EDL,
plus a full traceable adapter bundle. The unchanged original
story_first_search.discover_story_first is invoked with api=None, which
prepares real interval requests without HTTP. Original validate_render_rows
and adjacent_story_anchor_pairs are also called. No model/clip generation
or historical V3-R rerun.

- Non-goal semantic anchors use the actual predicate, never a fake goal.
- Each localized required graph anchor maps to an existing EDL segment.
  Preserve all material associations; select one representative segment
  per semantic anchor for the original P1 adjacent-anchor contract.
- Required context is distinct from anchor; missing actions have no
  virtual media rows. Their observation tasks remain in the bundle.
- For comeback, default auto uses four historical action candidates
  (78s in A/B), preserving the original 89s native plan independently.
  The three scoreboard-confirmation windows are not goal actions.
  Legacy synthetic event IDs are retained separately; native atom IDs
  are mapped by source PTS. Explicit --seed r3 uses new anchor material.
- Replay/slow-motion overlaps are reported, not silently removed or
  rendered. These are unverified candidate windows, not certified LIVE.
- Preserve exact native event document (including nonlive rows) for old
  P1/P2. Check every frozen evidence atom against original ID/window/time.
- Full graph, short chains, context pool, observation tasks and source
  hashes are retained separately. Compact graph semantics enter native
  story plan. The original P1 plan-reference length cap remains unchanged.

## Cursor: first integration preflight (zero HTTP)

    cd research/sportscausal
    python -m unittest -v test_r3_legacy_agent_adapter

Expected 8 tests; actual count/results are authoritative.

Run once for these four frozen R3 stories:
A/comeback__1, A/keeper_rescue__2, A/turnover_to_goal__1,
B/equalization__1. Example:

    python r3_legacy_agent_adapter.py \
      --story-dir artifacts/v3r_general_r3_preflight/A/keeper_rescue__2 \
      --evidence artifacts/stage1_2_evidence_preflight_20261125/A_uae_oman/keeper_rescue/evidence.json \
      --events ACTUAL_STAGE1_2_NATIVE_ENRICHED_EVENTS_JSON \
      --algo-dir ../../11.20sstory_chain/algo \
      --allow-dev --out-dir artifacts/v3r_legacy_agent_adapter_preflight/A_keeper_rescue

For B use B_osasuna_celta evidence, its native source events and corresponding
story folder. Use original source files; no reconstruction or historical
recomputation. Do not run the cf397a7 experimental single-loop agent.
Do not decode/render videos or call paid HTTP in this preflight.

Expected from frozen R3 (do not force results):
- A comeback: 4 action candidates / 78s, 3 semantic anchors / 2 adjacent pairs.
- A keeper rescue: 6 segments / 70.530s, 6 anchors / 5 adjacent pairs.
- A turnover: 5 segments / 23.542s, 2 anchors / 1 pair; all 7 atom IDs preserved.
- B equalization: 1 segment / 3.840s, 1 localized anchor, missing score:2
  and observe:5 retained; no adjacent pair. Existing P1 cannot bridge an
  unlocalized anchor; original Goal Recovery connection remains pending.
- Report actual interval scope/status and full event inventory counts.
  An INVALID_INTERVAL/INSUFFICIENT_EVENTS is an actual result, not a pass.
- Audit all source overlap diagnostics, legacy source binding, task count,
  and exact unchanged source windows. Do not treat them as verified clips.
- Return actual unittest.txt, REPORT.md, commands, hashes and all adapter
  outputs including original_p1 generator requests. Preserve original code.

## Next integration work (not claimed done)
The adapter outputs native plan/EDL and real original P1 request preparation,
not an end-to-end run. Original story_e2e_agent.StoryE2EInputs already
accepts baseline_edl, story_plan, initial_story_mp4 and events_json without
run_fresh_v3r. Need align/render the initial preview using original renderer
and pass these inputs. Need adapt goal-specific Critic behavior and required
anchor protection only at relevant Critic/Planner points (do not change
shared Verifier semantics); connect R3 missing/task context to original goal
recovery/search, support relation/phase targets, and check actual baseline
plan/EDL timeline. Do not turn every missing action into a new fake EDL row.
Do not change the original P1/P2/P3 algorithms, loop update/termination
or Verifier. Final real cross-template run and quality vs outer round
count remain unvalidated. No claim of FIRST_LIVE or final delivery.
