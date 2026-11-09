# Phase 8 approved real VLM experiment — single bounded authorization

User consent: 2026-11-09, '可以', in direct response to the proposal of ONE controlled multi-round VLM experiment, at most 5 HTTP attempts, at most US$0.10 code-estimated spend, at most 3 rounds. The user confirmed two precise candidate first-live clips by personal video review. This document grants no additional experiments, retries beyond zero, expansion of budget, or public release.

## Freeze and prerequisites (must finish before the first paid request)

- Branch `story-va-v3a-phase8-loop-impl`, last verified baseline commit before this runbook `9c049e1b8083af770e6ed9be322e7fe00d56985f` (do not assume that is the current tip). Never touch V1/V2 or Phase9.
- Freeze original UAE–Oman source MP4 whose expected sha256 is `a66147f79609c8fbf831a8bd29de4c6d7f746b314b2b18a88ffb1fc5f319da9c`, match JSON, existing atomic enrichment output, initial Phase5 EDL/plan/story_clean.mp4, model and sampling settings. Record hashes and code SHA.
- Use the existing enriched events `01_to_04_fresh_v3r/01_enrich/events_enriched.json` (879 events, including 130 `atom_fill`); NEVER reimplement enrichment. Ensure V3-A Search resolves this file.
- User attestation: `docs/phase8_review_artifacts/visual_compare_20261109/USER_FIRST_LIVE_REVIEW_ATTESTATION.json`. Two exact windows: Defensive_action 6400.90–6412.50 and Shot 2273.20–2290.41. This is a human first-broadcast determination for those two windows ONLY; not whole match authorization. Load the original source MP4, hash it, and link exact window evidence packs with byte hashes and timeline review records to the validator. If the actual EDL window differs, requires different frames, or is extended, status must be UNKNOWN pending independent review. Do not simply inject a first-live boolean or bypass `build_first_live_window_ledger`.
- All other hard gates must be satisfied or stay UNKNOWN/FAIL: no replay/slo-mo, protected goals intact, source PTS, EDL/candidate MP4 alignment, render succeeds and version digest checks. Even if video quality is improved, UNKNOWN may not be promoted as approved/deliverable.

## Execution bug to fix/test before any HTTP

- `story_e2e_cli.py` currently declares `--offline` with `action='store_true', default=True`: setting `--enable-real-api` does not turn `args.offline` off, so `skip_vlm=True` still applies. Correct it with a minimal and backward-compatible CLI mode rule and tests. Never claim a paid model was used unless provider receipt confirms.
- `StoryE2EInputs.phase8_paid_multi_round=False` is enforced in `story_e2e_agent.py` when `max_rounds>1` with real API, but CLI does not expose `--phase8-paid-multi-round`. Add a narrowly scoped explicit switch and unit test. Do not enable it by default.
- CLI currently does not expose `first_live_evidence_dir`; add a controlled parameter or use the existing programmatic entrypoint with auditable input artifacts. Rehearse the entire command with a fixture/stub and assert **zero network**, correct provenance and all gates. Validate that spending counters actually persist and stop before the sixth call / attempted excess cost. If the API adapter cannot guarantee a hard billing cap, describe estimation uncertainty and stop conservatively.
- Run full Phase8 tests, including replay-priority/routing and a test specifically asserting real mode never resolves to `skip_vlm=True`. If any fails, STOP; no paid requests.

## Approved single experiment

- Exactly ONE paid evaluation job for the previously confirmed match/story. Max rounds=3 (target 2; third only if algorithm continuation and remaining budget permit). Max HTTP attempts across all components of this ONE run=5. Max code-estimated USD=0.10. max_retries=0. No sequential separate runs that each reset the 5-call cap.
- The API/VLM must receive actual original- and candidate-video observation frames, not narrative fixture outputs. Run existing Critic → Evidence Search → Planner → Verifier feedback loop autonomously; no manual scripting of which candidate A/B should win.
- Proposed revisions must be verified at exact source PTS, with no replay/slowmo, protected goals and other safety invariants. Before-first-LIVE evidence applies only to exact two reviewed windows. Unknown new candidates must be rejected or requested for additional review, not silently approved.
- Never treat a VLM soft PROMISING rating as hard-safety approval or release authorization. Hard-safety gates, acceptance and best-version promotion remain independently audited.
- Keep baseline frozen; record EDL / MP4 hashes and per-round best/working lineage, selected issue/window, actual visual frames, HTTP attempt count, usage/cost, verifier payload, failure feedback, stop reason and release decision.
- The user's yes authorizes paid testing only, not external publication, formal release or permanent deployment. `release_authorized` remains false until ALL release-grade gates pass and a separate delivery decision is made.

## Success/failure output

- Source/code hashes and exact CLI invocation/config (with secrets redacted); unit/regression results and API-mode dry-run.
- One actual `run_story_e2e` output tree, roundwise audit and true provider usage/receipts, with totals and hard stop; no invented result if call fails.
- Initial vs best selected EDL/MP4; for each revision, evidence of first-LIVE, goal preservation, temporal provenance, narrative change and issue resolution. Include two small *playable* video clips or the full render plus a 1–5 human storytelling review sheet covering buildup, transition, post-goal cohesion, pacing.
- Classify each change: accepted-safe-improved / rejected-unsafe / rejected-low-quality / unverified. Without an independently reviewed story-quality comparison do not claim end-to-end improvement.
- Preserve all output files under a new run-specific directory, do not overwrite history. Stop and report if code/config/permission/preconditions cannot be verified. No additional user permission is necessary for the single run within this exact budget, but exceeding any limit requires a new explicit user approval.

## Authorizations / non-authorizations

Authorized: 1 run, <=3 rounds, <=5 HTTP attempts, <=US$0.10 code-estimated, zero retries, given match only, no gold.
Not authorized: $0.25 / 12 calls, a second paid ablation job, other matches, repeated paid tests, Phase9, mutation of V1/V2, use of manually annotated story gold, bypass of first-live gate, or production release.

CRITICAL: ChatGPT cannot launch or monitor the user's private GPU/media server here. Cursor on the user's server must do preflight/paid execution and return real logs.