# Phase 8 — Cursor execution handoff

Follow the design spec at docs/PHASE8_FAILURE_AWARE_ITERATIVE_STORY_REVISION_DESIGN.md in this same branch; treat it as the architecture contract. This handoff does not authorize paid APIs or modification of V1/V2.

## First response to ChatGPT (BEFORE large code changes)

Send a compact factual inspection report, not just an affirmation:

1. git branch --show-current; git rev-parse HEAD; git status --short. If local changes exist, preserve them and isolate implementation in a new worktree/branch. NEVER overwrite local changes.
2. Identify actual pytest targets/paths for V3-A main loop, evidence search, paid planner, visual verifier, final delivery. Show current PASS/FAIL with exact command, or explain missing dependencies.
3. Inspect latest Phase7 local artifact examples: 02_round_*/revision_cases.json, verifier_report.json, revision_plan.json, evidence_search.json and llm_verifier.json. Report keys/source status and whether real evidence exists. Distinguish NOT_EVALUATED from confirmed WORSE.
4. Report any spec-to-code mismatch before implementing, especially legacy fields read by CLI and final release gate.

No need to send MP4s yet.

## Work order (no paid API)

Commit 1: pure story_revision_feedback.py + story_loop_policy.py and deterministic unit tests.
Commit 2: feedback-aware evidence search, local planner, paid planner prompt wiring; preserve existing defaults and old signatures. Tests.
Commit 3: main loop working/best version registry + explicit transition reasons + snapshots; no immediate break on unaccepted candidate. Tests.
Commit 4: Verifier phase8_verdict and final delivery selected-version semantics; hard safety remains fail-closed. Tests.
Commit 5 only if needed: fix compatibility/review bundle issues found by integration tests.

Do not add another top-level pipeline. All processing remains in run_story_e2e and original accepted V3-A import paths.

## Return format after implementation

- Implementation branch + HEAD commit URL
- Changed files and behavior mapping to Spec sections 1–7
- Exact offline test commands and pass/fail counts
- Phase8 loop fixture JSON showing r1 PROMISING or UNCERTAIN -> feedback -> r2 DIFFERENT action -> legitimate stop / r3
- Two distinct source candidates or a reason why none can be found, plus zero-HTTP proof
- Version lineage: initial, working, best, delivered; final EDL and MP4 refer to same selected version
- Hard-gate test results: first LIVE/replay/slowmo/PTS/protected goals
- Known unresolved items, production risk, estimated API budget for a FUTURE run (do not execute it yet)

## No false success

A synthetic fixture proving the loop control flow is NOT an actual better video. Separately report structural_loop_pass, video_semantic_quality_verified, unseen_match_generalization_verified, and release_authorized. The latter three cannot become true just from fixture tests.

If the design needs a change, provide the specific code conflict and a proposed correction; do not silently weaken the first-LIVE or delivery requirements.
