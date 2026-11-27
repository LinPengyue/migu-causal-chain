# Fresh V3-R-General entry (single native source video)

This is an additive research-only entry. It closes the missing engineering link
between native delivery events/MP4 and the already implemented R1–R3. It does not
implement the proposed R2-L composition layer, change any operator, rerun A/B,
or execute old T01 Phase5 or the Story Agent.

## Input contract

- Native delivery JSON with unique event IDs, both team records and source-media
  seconds; exact corresponding original video, one source per run.
- Development (same regime as historical A/B): original human short-chain JSON
  via `--causal-atoms-json` + `--allow-dev`. The frozen enrich function extracts
  atomic facts only, deduplicates and merges them. The resulting prediction
  input is still **gold-derived development data**, not an independent test.
- Independent event annotations: `--independent-atoms-json`, mutually exclusive
  with causal-derived atoms. Raw only: omit both. Do not silently fall back to
  raw-only when testing the historical development regime.
- Score-side mapping: use a native explicit mapping if provided; otherwise pass
  verified `--score-left-team team_1|team_2` and
  `--score-mapping-provenance`. Do not guess based on a filename or use a
  reference story. A score path is generated from this run's enriched events
  by the original stable score extractor, not a T01 output/cache.
- Optional expected SHA256 values for video, raw events and supplement input
  prevent accidental changes when source identities have already been checked.
  The entry records actual paths and hashes, but the caller must establish
  same-match/source identity. Split-half files must have individually matching
  event axes; no automatic concatenation or timeline translation is implemented.
- Fresh output directory required. A failure after stage start preserves a
  FAILED run manifest; no hidden retry, no reuse of partially generated data.

## Exact module chain

01_enrich: original atomic_event_enrich.enrich_files
02_strip831: original closed_loop_cli._run_strip (production profile,
rule-only, sliding recall; no paid LLM)
03_v1_adapt: original closed_loop_cli._adapt_v1 (including Goal Recovery)
04_evidence: original research build_evidence + original score_path.build_score_path
05_r1: normalize_for_episodes
06_r2a4: role-safe fresh graph, no historical score-contaminated graph or cache
07_r2bc: unchanged six templates
08_r3: unchanged compiler and materializer, all 8 supported template types plus
separate mixed score-context hypothesis. By default no legacy seed; optional
--legacy-seed-manifest preserves an existing original comeback seed byte-for-byte.
It does not automatically generate a new T01 seed or replace the original delivery entry.

The old Phase5-only replay-goal filter is not inserted into the research
pipeline; the full adapted prediction is consumed by the existing Evidence
availability/replay policy as in historical A/B. R3 media remain previews, not
certified FIRST_LIVE. The old Phase5 rendering/goal visual audits are not run.
This is not a complete 17-template runner yet, nor a formal evaluation runner.

## Server smoke and new match validation

From a clean research worktree with frozen delivery ref available locally,
with original delivery dependencies and ffprobe installed:

    cd research/sportscausal
    python -m py_compile run_fresh_v3r_general.py test_run_fresh_v3r_general.py
    python -m unittest -v test_run_fresh_v3r_general

The new tests mock video probing and delivery calls while running real research
R1–R3. They are not a substitute for a real upstream integration run. Record
actual stdout and exit status. Do not rerun historical A/B paid experiments.

For C_levante_rayo, confirm the original event file and same-source human
short-chain annotation file. Use the independently verified mapping from
intake. Example shell (variables are actual server paths, not guesses):

    python run_fresh_v3r_general.py \
      --match-json "$C_RAW_EVENTS" \
      --causal-atoms-json "$C_HUMAN_CAUSAL_ATOMS" --allow-dev \
      --source-mp4 "$C_VIDEO" \
      --expected-source-sha256 5ab8ee77ed0d0cb56f020348d4c73b4c27c738f6285db941e1797f87bb1d4d73 \
      --score-left-team "$C_VERIFIED_LEFT_TEAM" \
      --score-mapping-provenance "$C_MAPPING_EVIDENCE" \
      --out-dir artifacts/v3r_general_C_levante_rayo/fresh_general_v1

Use original native event JSON (443 events), not benchmark reference story
or gold-clips evaluation dump. Do not provide human chains to strip inference
or R2. No gold story labels as inputs. Compare generated score trajectory
against intake, not as an override. Return actual command, tests, run_manifest,
01–08 stage outputs, and per-template R3 summary. Report all new atom IDs,
types and phases, full/partial/unavailable/nonlive short-chain counts,
unlocalized score steps and turnover candidate member paths. Do not infer
quality from candidate count or longer duration. Render turnover candidates
separately with the existing R3 adapter and preview renderer only after the
upstream run succeeds; no Story-First calls.

The entry optionally accepts repeatable `--template-id` for filtering the final
R3 output (all upstream discovery still runs). Default is all 8 types and the
separate mixed hypothesis. New matches need no A/B paths, T01 file, or manually
prepared predicted-causal file.

GitHub code written and reviewed; actual server tests and C run are pending.

## Compatibility audit (frozen A/B, not a new experiment)

Run only the new regression audit against the frozen evidence and R1–R3 artifacts:

    python audit_fresh_v3r_compatibility.py --out-dir artifacts/fresh_v3r_compatibility_v1

Optionally add --a-events "$A_EVENTS_ENRICHED" --b-events "$B_EVENTS_ENRICHED"
using the exact historical enriched event files, not newly enriched copies.
This adds a comparison of regenerated score rows, including carrier IDs and
previous observations. Without those paths score regeneration is explicitly
not checked. The upstream enrich/strip/adapter, videos, and paid Agent are
not rerun. The audit recomputes only in-memory research stages and writes
separate outputs. Inspect all differences, not only the exit status.
The new fresh entry accepts --legacy-seed-manifest using the existing R3 schema;
it rejects a filter excluding comeback and retains the original seed bytes.
For new comeback matches lacking a legacy seed, continue using the original
11.20 delivery workflow for its verified behavior; the new R3 anchor preview
is not an equivalent substitute.
