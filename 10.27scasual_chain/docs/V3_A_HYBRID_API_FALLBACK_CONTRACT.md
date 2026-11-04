# V3-A Hybrid Agent: API-primary, rule-supported fault tolerance

Date: 2026-11-04. Agreed architecture: `V3_A_AGREED_DESIGN_CONTRACT.md`.
Baseline: `story-va-v3-r-frozen-20261103` at `2d1ec9c2a409e681aec9942332b3509fe054b887`.

## Core objective and nonnegotiable semantics

V3-R remains the reproducible initial story and trusted production continuation. V3-A seeks incremental, model-driven improvements: real LLM Planner analysis, conditional real VLM observations, model Verifier + independent hard constraints, at most three repair rounds.

**API outage must not stop the entire deliverable workflow. However, absence of API cannot be misrepresented as model verification or as evidence of actual story-quality improvement.** Separate workflow completion, structural checking, media verification and model-improved outcomes into independent statuses.

### 1. Primary + graceful fallback by component

| Component | Preferred real mode | During timeout/502/budget exhaustion | Limit of rule mode |
| --- | --- | --- | --- |
| Planner | LLM diagnoses missing beats, suboptimal transitions and requests evidence-backed edits | Retain V3-R story/EDL, run deterministic known-issue detection and safe bounded tool task generation; emit `PLANNER_RULE_FALLBACK` | Cannot claim newly discovered semantic omissions or agent improvement |
| VLM + video tools | Model observes sampled frames or targeted contiguous video and suggests next observation | FFmpeg/tool execution and existing validated event / scoreboard constraints continue; mark visual semantics `UNKNOWN`; reuse only explicitly provenance-labelled, still-applicable evidence | OCR/time and codec checks do not prove first-LIVE goal or story relevance |
| Verifier | Model gives three-dimension evidence-referenced judgments plus independent rule hard vetoes | Re-run rule checks and technical QC; mark narrative semantics `NOT_EVALUATED`, issue `VERIFIER_RULE_FALLBACK` | No model-quality score, no invented verified LIVE, no automatic approval of a model-dependent patch |
| Composer/EDL | Evidence-bound local proposal and re-render in isolated workdir | Keep best previously **accepted** revision, or fall back to unchanged V3-R baseline candidate; report unresolved work | Never silently mutate frozen artifacts |

Optional secondary API provider may be used only if already configured and explicitly within the same user-approved budget, with model/provider recorded; do not silently reroute billable requests or use mock/cache responses as fresh real observations.

### 2. Dual-track Verifier and decision levels

**Rule track (always run):** T01 selected-arc coverage **structural proxy**, factual scoreboard/team constraints, LIVE/replay metadata exclusions, nonnegative & in-bounds EDL windows, duplicated goal mapping, file/source provenance and hashes, FFmpeg decode/integrity warnings, protected important goal segments and previously accepted regressions.

**API track (if available):** story-element real visual coverage, semantic narrative coherence, omission/shot relevance, actual image-content quality. Require valid evidence references and explicit UNKNOWN for uninspected elements. A model-produced numerical score alone is insufficient.

Keep strict independent hard vetoes. At minimum:

- `BLOCKED_HARD_GATE`: independent P0 failure; do not authorize candidate.
- `MODEL_VERIFIED_CANDIDATE`: rule track passes, model track passes, independently supported improvement, no regressions; still not automatically production render-ready.
- `RULE_ONLY_BASELINE`: API track unavailable, baseline (or previously independently approved artifact) is preserved; ordinary V3-R candidate delivery may continue, **without** claiming semantic/VLM verification.
- `NEEDS_MODEL_OR_HUMAN_REVIEW`: new material visual or narrative edit cannot be independently supported in API-degraded state; keep as proposal, do not accept or release it.

Separate fields: `workflow_completed`, `provider_mode_by_role`, `fallback_reason`, `rule_hard_gate_pass`, `semantic_verification_status`, `edl_candidate_status`, `agent_contributed_improvement`, `render_ready` and `release_decision`. Do not overload a single `success` boolean.

### 3. Round and failure policy

- API call: bounded retry only for transient error (e.g. 502/503/timeouts); no open-ended waits, no unbudgeted retries. Record every attempt, provider response and total usage.
- Planner API failure: use deterministic V3-R plan, optionally rule-detected evidence tasks; do not create new semantic editing intents. Continue report/QC/fallback delivery.
- VLM failure: video tools and rule checks may continue; preserve `UNKNOWN`, do not fill goal times or claim first LIVE based on a single frame, OCR or previous rejected Goal@1351 atom.
- Verifier failure: rule Verifier **must run** and produce diagnostics. Do not mark model verification successful. If the edit requires semantics/visual correctness, do not accept that edit; retain last accepted EDL or frozen baseline.
- API may recover in later round within the *same capped budget*: resume from last accepted EDL, retain failed request trace, and do not count rule-only fallback as a productive Agent revision.
- Exhaustion after up to 3 rounds: deliver unchanged V3-R candidate or best previously independently accepted candidate plus failed-gate report; never force formal release.
- Protect all original V3-R code, inputs, EDL, source video and MP4; write V3-A results into isolated non-overwriting output dirs.

### 4. Acceptance and quality measurement

Quality improvement path needs an actual changed candidate, source-time evidence, no new P0, preservation of previously correct segments, and an independently corroborated target improvement. For pure semantic improvement, no available real model **and** no independent human review => keep pending, not accepted. Rule-only structure and FFmpeg proxy scores must be labelled accurately.

A degraded model call should decrease `availability_of_ai_qc`, not fabricate poor score=0 or good score=100. Distinguish `NOT_MEASURED` from `FAILED_QC`.

### 5. Required tests before further paid trials

1. Planner 502: fallback V3-R output, known-issue rule tasks and complete logs; no agent-success claim.
2. VLM 502: keep precise frame/PTS provenance, visual UNKNOWN, no invented LIVE claim, possible subsequent evidence search.
3. Verifier 502: rule-track metrics/hard veto still generated; model track NOT_EVALUATED; no semantically dependent edit accepted.
4. All APIs down: pipeline completes with baseline candidate + diagnostic report, without freezing the whole orchestration; no new EDL acceptance.
5. API recovers: capped later round can proceed without resetting to unsupported candidate or corrupting best accepted EDL.
6. Correctly verified, low-risk non-semantic edits: policy permits only if independently checkable and explicitly authorized; never infer broad semantic quality gain from structural proxy.
7. Budget exhausted, malformed JSON, mock/cache response, replay as LIVE, wrong team/score, source-file drift: fail closed on the claim; degrade operationally without changing frozen output.
8. Independent V3-R/V3-A hashes match original, and every fallback output exposes reason and provider modes.

### 6. Known current implementation delta (audit 879b633)

`call_llm_verifier` retries transient 502 but `decide_accept` returns `accept=false` on verifier failure; `run_self_revise` aborts after Planner failure. These are reasonable fail-closed decisions **for edited candidate acceptance** but not yet complete graceful degradation to a finished baseline + audited report. Implement two-track Verifier and orchestrator-level fallback with separate statuses, without turning fallback into fake Agent improvements.

Separate preexisting Stage-3 test fixture failure: test fixture assigned the same mutable hashes dict to proposed snapshot and observed hashes; changing the observed hash changed both. Use a copy to actually test drift rejection, then run the full suite and show results. Do not mislabel this as proof the hash safety gate was broken.
