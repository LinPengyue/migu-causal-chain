# Eight implemented templates: end-to-end development validation

Frozen algorithm baseline: 69f0c4d2ce36cb9ba2e9493d041e8a80138d5dc6.
FanEdit v1.1 frozen reference: e67d7c9f596db5b3cd5618f4692733126e68b1c1.
No change to reference annotations, five operators, delivery code, initial anchor
policy, original P1–P3, verifier or main/outer loops. No new template work yet.

## Existing evidence: preserve, do not rerun

The registry `validation/fanedit_v1_1_e2e_registry.json` indexes eight templates,
historical comeback previews (four development matches), A/B 89s legacy seed
hashes, actual keeper run with v0-v3 media paths and hashes, compatibility
checks and failed/partial cases. Keeper selected preview is human-positive
but formal release is BLOCKED and first-live not certified. Original comeback
delivery previews are not proof of a new general-entry paid loop. Existing
legacy seed compatibility is verified; do not claim automatic seed generation.
Preserve these distinctions in all reports.

Server archive step: copy or retain immutable versioned MP4/EDL artifacts
(including rejected, unchanged or budget-limited versions), verify hashes,
record full path, bytes, duration and source match/video IDs; never regenerate
a missing historical artifact to pretend it is the original. Copy JSON audit
files, configurations, command, model IDs and actual costs. Do not commit
large media; record stable server/archive paths and hashes. If missing, mark
MISSING. Existing registry indexes Git evidence; media still needs verification.

## 1. Choose six appropriate matches

From the local frozen benchmark worktree:

    python select_e2e_dev_cases.py \
      --benchmark-dir "$FANEDIT_V11_DIR" \
      --video-root /mnt/data4/migu \
      --out artifacts/e2e_validation_v1/case_inventory.json

Check all six lists. The script verifies three pinned benchmark file digests,
uses only reference category/subtype to shortlist single-source matches, and
does not export gold clips, event lists or score paths. File-name matches are
unverified. Prefer already-exposed matches with verified full original videos
and same-source native annotations. Select one suitable available match per
template before running. Reuse frozen compatible R3 artifacts only when
their match is suitable; no A/B reruns solely to generate identical candidates.
If no full video/source alignment, return candidate match names and blockers.
Never use a stitched half-time timeline or wrong video. For turnover, do
not repeat C zero-candidate or A short initial render; use another suitable
reference match. Spain–Germany, Oviedo–Real Madrid and Croatia–Morocco
are prior turnover shortlist examples, verify the exact reference and source.
For other templates, do not assume A/B's automatically generated candidate
is a positive reference; shortlist first. All selected or inspected development
matches must be logged as exposed at match level, including failed runs.
Do not pass reference story annotations or windows to inference.

## 2. Run V3-R once per new match

Use run_fresh_v3r_general.py from the frozen algorithm baseline, with original
event JSON, original video, same-source human short-chain atom supplement
(--causal-atoms-json --allow-dev), verified scoreboard mapping, source hashes,
fresh directory. Use identical production rule-only 8.31 profile. If a suitable
match has already run fresh V3-R with identical inputs, reuse all artifacts.
Run all 8 templates once, not once per template. Keep every predicted
candidate and zero count; no reference clips, manual seed injection, threshold
changes, or multiple attempts selecting the prettiest result. Pick a target
candidate using predicted structure and template, not reference temporal
overlap; log selection and other candidates. If no candidate, record discovery
failure and stop that case. An E2E failure is a legitimate outcome.

## 3. Real original Agent on a selected candidate

For new candidate, use existing R4/R5 overlay and critic preflight exactly
as documented in R3_CRITIC_ADAPTER_R4R5_2.md. No new agent implementation.

    python stage_r3_critic_adapter.py \
      --algo-dir ../../11.20sstory_chain/algo --out-dir "$OVERLAY_DIR"
    python r3_critic_preflight.py \
      --story-dir "$R3_STORY_DIR" --evidence "$EVIDENCE" \
      --events "$ENRICHED_EVENTS" --algo-dir "$OVERLAY_DIR/algo" \
      --allow-dev --out-dir "$CRITIC_PACK"

If compatible existing critic pack is available, reuse exactly. Confirm actual
template context survives serialization, required segments preserved, goal
coverage scoped to story. The original runner checks source SHA and duration;
provide an actual trusted verified source manifest. For each real case invoke:

    python run_r3_original_agent.py \
      --pack "$CRITIC_PACK" --evidence "$EVIDENCE" \
      --events "$ENRICHED_EVENTS" --match-json "$RAW_EVENTS" \
      --source "$SOURCE_MP4" --source-manifest "$SOURCE_MANIFEST" \
      --original-algo ../../11.20sstory_chain/algo --allow-dev \
      --out-dir "$NEW_RUN_DIR" \
      --main-rounds 3 --outer-rounds 3

Default is render-only, NOT full E2E. Once paid execution is explicitly
authorized, add --enable-real-api --approve-budget --max-calls 24
--max-cost-usd 0.10. If already rendered, use exact --prepared-dir
with new run dir, not re-rendering V0. Six-case proposed maximum 144 HTTP
attempts and USD 0.60 estimated, not actual billing or approval. Stop on
budget/exception, do not auto-retry. Follow actual native decisions, do not
force revisions if no improvement needed. Actual P3/outer attempts may be
fewer due to early stop or budget. Record exact stage reached.

## 4. Acceptance and record keeping

Per case store run_manifest, inputs and SHA256, R1/R2 candidates and R3 graph,
v0 and selected final EDL, actual MP4 paths/bytes/sha/duration, intermediate
versions, P1/P2/P3/verifier evidence, actual executed rounds and costs, elapsed
time, native delivery verdict, human narrative/continuity/faithfulness/first-live
review, failure reasons. Report each stage separately:
DISCOVERY_FAILED, SEED_RENDERED, AGENT_RETURNED, HUMAN_REVIEW_REQUIRED,
HUMAN_POSITIVE_PREVIEW, HUMAN_REJECTED, plus independent first-live and release
status. Never infer quality from output length or ACCEPTED_PREVIEW. Human
must inspect actual video; valid story requires correct template, subject,
long-range narrative (not only one short path), coherent footage, no replay,
no fabricated events, and retained required actions. A no-change run can
be valid if V0 already meets the criteria. For each of six templates require
one positive human-reviewed result before calling it validated; report
failures rather than silently switching examples.

Preserve all predictions, not just selected positive previews. Store immutable
per-run entries and update registry by adding records, never overwrite old
results. FanEdit diagnostics may be calculated after inference with the exact
frozen benchmark and separate evaluation protocol. Export match_id, category,
subtype, ordered final segments with native source video_id and media seconds;
map original event IDs to video_id:E:source_event_id using the frozen inventory.
Never fabricate a mapping for atom_fill or unmatched event IDs; report mapping
coverage and retain prediction window. Preserve separate R3 and final predictions
and unselected predictions. Do not report template-conditioned development
preview scores as held-out performance. Add all selected/inspected match IDs
to development exposure ledger without rewriting FanEdit v1.1. C is already
an additional known dev exposure beyond the four original matches.

## Current status

Registry and shortlist utility authored in Git. New six E2E runs, server media
archival, and actual shortlist execution are pending on server. No additional
HTTP calls or historical rerun were performed by the author. Existing gate
final_edl_missing_goal_anchors on keeper preview remains a real limitation;
do not bypass to manufacture a release. Retain legacy comeback route for
already verified behavior.
