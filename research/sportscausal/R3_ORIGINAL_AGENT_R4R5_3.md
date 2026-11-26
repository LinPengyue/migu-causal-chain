# R4/R5.3 — original Story Agent, real video integration

Freeze R4/R5.2: 277620a5236bcf8618cdd6915592af5b5130af6b.
Use its actual story_plan.json / candidate_edl.json without rebuilding
R1-R3 or repeating adapter preflight. The source event/evidence hashes
must match its report. Original source footage must match a source SHA
from a trustworthy historical run/source manifest (not just a newly
computed hash of a guessed filename). Keep the original match JSON.

run_r3_original_agent.py invokes original _render_edl and run_story_e2e.
It stages the already tested R4/R5.2 overlay, with one metadata-only
addition at the two data_tier call sites: propagate the actual R3 tier
instead of calling human-enriched development data raw-only. P1/P2/P3,
outer loop, Verifier and Timeline stay byte-identical. It does not
call the cf397a7 experimental loop or legacy V3-R builder.

## Primary experiment: A keeper_rescue:2

Choose a non-comeback story to test transfer; not another historical
comeback run. Frozen 6 segments, 70.530s, 5 adjacent intervals. No
whole-match goal repair requested. Real generation, Planner selection,
source review, trial rendering, P3 local trim, then original outer
continuation. Preserve the original native preview/quality decisions.

Source manifest JSON: {"video_id": exact evidence video_id,
"sha256": trusted historical source hash, "provenance": reference to
the actual historical source audit/file mapping}. Cursor must verify
actual source path/hash against trusted previous run, not manufacture
a match from duration. The runner also checks actual duration.

From research/sportscausal:
    A_EVENTS=/data2/lpy1/_story_va_outputs/v3/plan2/full_e2e_A_strict_lin_20261108_095704/01_to_04_fresh_v3r/01_enrich/events_enriched.json
    A_EV=artifacts/stage1_2_evidence_preflight_20261125/A_uae_oman/keeper_rescue/evidence.json
    python run_r3_original_agent.py \
      --pack artifacts/v3r_critic_adapter_preflight/A_keeper_rescue \
      --evidence "$A_EV" --events "$A_EVENTS" \
      --match-json "$A_ORIGINAL_MATCH_JSON" --source "$A_ORIGINAL_MP4" \
      --source-manifest "$A_SOURCE_MANIFEST" \
      --original-algo ../../11.20sstory_chain/algo --allow-dev \
      --out-dir "$NEW_RUN_DIR"

Default is actual render only, zero paid HTTP. If explicitly approved,
add these flags to the SAME initial invocation, or use --prepared-dir
pointing to an exact prior render-only output and a fresh out-dir:

    --enable-real-api --approve-budget --outer-rounds 3 \
      --max-calls 24 --max-cost-usd 0.10

This is one run, not three independent calls. The frozen provider
allows <=24 calls when Story-First is enabled and cost estimate <=0.10
USD, retries=0. Formal main loop max_rounds=1; outer rounds=3 is the
separate Story-First expansion knob. P3 keeps its original local-trim
budget policy. These are caps and requested rounds, not guarantees of
completion or final actual billing. Do not loosen limits or automatically
rerun after partial/failed results. If budget has not been authorized,
execute render-only and retain the seed. No automatic extra case.

## Actual evidence required

Report input_provenance, render_manifest, overlay_manifest, original
agent audit, actual P1 requests/responses/valid hypotheses and source
review evidence, P3 caption/trim actions, outer comparison JSON and
v0-v3 EDL + actual videos where available. Preserve server paths/hash
for videos (do not commit huge MP4s). Include all rejected/no-op and
budget-limited branches. Record per-stage actual HTTP/cost and final
provider usage. Report native final delivery separately from research
selected previews. ACCEPTED_PREVIEW is not proven narrative improvement,
FIRST_LIVE certification or release authorization. No human/reference
story labels. No fixture/model mocks or extra Verifier invocation.

Review each available prefix from a single run: new footage and event
IDs, actual causal/narrative function, duplicates, clip completeness
and transitions. Human assesses v0-v3; longer is not inherently better.
If no native outer comparison exists, report first failure point and
preserve the initial video, not fictitious versions. If all three
iterations cannot run within original budget, report actual attempts.

## Other cases, later
- A turnover: source continuity and short path enrichment (5/23.542s).
- B equalization: native goal_coverage_01_to_11, original search
  [2488.6,2660.32]; currently one anchor, so not a Story-First loop test.
  Existing Goal Recovery still needs real video/first-live evidence.
  Optional --enable-native-broadcast-observation uses original opt-in
  only when separately authorized; no guarantee of actual repair.
- A comeback: legacy regression only if a new purpose warrants it.

No new general relation/phase-specific Observer routing is claimed.
Actual R3 observation tasks beyond legacy goal coverage and existing
Story-First source review remain a future integration question. This
experiment tests the preserved original agent rather than new gates.
