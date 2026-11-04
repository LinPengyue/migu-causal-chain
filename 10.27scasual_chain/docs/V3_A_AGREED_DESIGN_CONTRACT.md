# V3-A agreed architecture and non-regression contract

Status: **agreed design**, clarified 2026-11-04. This document records the previously agreed V3-A architecture, **not** a new direction. It supersedes any narrower interpretation of the incremental plan, especially treating rule-only fixes, France-only P0 recovery, or LLM task-ID ranking as the complete V3-A goal.

## 0. Starting point and nonnegotiable constraints

- Frozen V3-R: `story-va-v3-r-frozen-20261103`, commit `2d1ec9c2a409e681aec9942332b3509fe054b887`. Keep its code, inputs, EDLs, and candidate MP4s unchanged.
- Development: `story-va-v3-a` in isolation, with separate experiments and rendered artifacts.
- Preserve the original main path: atomic event enrichment -> 8.31 predicted causal chains -> T01 comeback story -> rule Composer -> candidate EDL/video. V3-A adds an **incremental agent revision layer**, it does not rebuild or replace a working V3-R by default.
- Previously agreed goal: improve story-element coverage, narrative coherence, and video quality through **real API LLM + VLM reasoning**, evidence gathering, feedback, controlled revisions, and a verifier, rather than continuing to increase handcrafted story rules.
- Only first broadcast LIVE action may be used as a primary scoring shot. Do not put replay / slow motion / replay camera angle into the delivered story. Scoreboard confirmation is not the goal-action timestamp. Human causal labels are not unconditionally trusted visual ground truth.

## 1. Planner: two connected responsibilities, not a generic unrestricted editor

**A. Initial story understanding and *incremental* revision planning.** Read T01, protagonist, score path, predicted causal chains, atomic event provenance, existing story beats, and V3-R story plan/EDL. LLM may independently identify omissions, poor transitions, insufficient setup, irrelevant footage, awkward ordering, and potentially valuable context. It may revise **narrative emphasis, local segment selection, transitions, and evidence requests**, while preserving confirmed score/team/event identity and successful original cuts. It is not limited to Stage-1 rule-detected issues: A/B/C must remain eligible for API-driven narrative diagnosis even when their structural proxies equal 100%.

**B. Diagnostic/tool planning and follow-up repairs.** Given Verifier findings, VLM observations and trace history, LLM chooses whether more evidence is needed, which tool/window to inspect, and whether to propose keep/add/replace/trim/reorder/drop/mark_unresolved. Every proposal has target IDs, rationale, expected story improvement, risks, and specific evidence references. Generated event/precise timestamps without tool evidence are rejected. A proposed edit is not automatically applied.

## 2. VLM and video tools: remedy missing/incorrect story evidence

- VLM's primary value is to analyze video for **missing story elements, inaccurate segment association, weak buildup, narrative discontinuity, relevant action/reaction**, and uncertain LIVE/replay status, not to redundantly classify every known goal.
- Distinguish: (i) known event but missing/mismatched video; (ii) missing event in predicted causal chain. Case (ii) triggers contextual, bounded, evidence-seeking inspection around narrative gaps; a newly suspected event stays `CANDIDATE/UNKNOWN` until independently grounded.
- Do not infer true causal relationships from mere temporal proximity. Separate video observations, input event assertions and verified findings. Retain timestamps/frame IDs, provenance and exact provider mode (real/mock/cache/degraded).

## 3. Observation feedback and conditional windows

- Default: **no unnecessary repeated search**.
- Trigger evidence search when concrete problems exist: event/video time conflict, absent mandatory shot or arc, missing/unconnected narrative context, disputed LIVE/replay, shot relevance mismatch, damaged source or output, or model/Verifier evidence insufficiency.
- Search first with available event/score anchors, then narrow or expand **only with recorded evidence or diagnosed uncertainty**. Predefined Stage-2 windows are search hints, not verified goal timestamps.
- Frame sampling is a tool, not evidence of nonexistence; if sparse samples miss a short action, schedule bounded high-density/contiguous-video checks before declaring unresolved.

## 4. Verifier: three-dimensional scores PLUS hard vetoes

Dimension 1, **story element coverage**: mandatory plot nodes, corresponding real video coverage, and causal linking shots. Show structural vs visual coverage separately; score UNKNOWN when not actually evaluated.

Dimension 2, **story/narrative coherence**: causal and temporal logic, transition continuity, story relevance, omission and redundant shots. Explicitly distinguish narration claims from demonstrated event relations.

Dimension 3, **image quality**: decoding and visible macroblocking, corruption, frozen/black frames, cut discontinuities. Expected title-card freeze is not damage. Use FFmpeg diagnostics plus real visual review as needed.

**Hard vetoes** override average scores: wrong team/score/attribution, replay falsely used as first LIVE, indispensable arc goal missing, invented evidence/times, severe validated corruption. Verifier must cite the affected cut and evidence, not issue an unsupported global numeric score. Model-generated ratings are not self-validating ground truth; calibrate with independent checks/manual review.

## 5. Maximum-three-round revision loop and rollback

V3-R original story -> LLM diagnosis & local proposal -> conditional Video Tools/VLM observations -> evidence-constrained candidate Composer/EDL -> Verifier (scores + hard vetoes) -> feedback to Planner if needed (maximum **three repair rounds**).

- Preserve every round: proposed change, observations, model/provider/cost, output candidate EDL, metrics, diffs and failure reasons.
- Accept a patch only if its intended defect demonstrably improves without P0 regression or significant damage to previously correct story segments. Otherwise rollback.
- If thresholds cannot be met in three rounds, keep the highest **audited** candidate and unresolved issues; no forced `render_ready=true` or product authorization.
- Compare against the untouched V3-R with identical inputs and an explicit API/video sampling budget. Track false improvements and bad repairs, not just successful render.

## 6. Development status versus the agreed end state

- **Stage-1:** completed and reported; structure-only Verifier 10/10 tests; A/B/C structure PASS, FR lacks opening opponent goal. Visual semantics remain UNKNOWN.
- **Stage-2:** completed offline and reported; 21/21 tests; current LLM interface can only rank prevalidated issue IDs. This does **not** fulfill Planner responsibility A, nor independent diagnosis on A/B/C.
- **Stage-3 first increment:** source-bounded frame search and optional VLM interface have been committed; actual source-media testing/approval and true VLM observations not yet demonstrated in the report available at authoring time. This France P0 probe is **a first case**, not the complete scope of V3-A.
- **Still required:** real API LLM-powered story diagnosis, genuine VLM evidence analysis, evidence-dependent local re-search, a gated patch application route, semantic Verifier, and the three-round rollback loop.

## 7. Next implementation and test priorities

1. Retain already written Stage-3 safety and time/provenance checks, but do not let additional rule tweaks substitute for the core architecture.
2. Build a **real API LLM Planner story diagnosis contract** on V3-R outputs, not just P0 issue ranking. On the France P0 it should identify missing loss context, prioritize recovery and produce bounded tool requests; on A/B/C it should review whether apparently complete stories have optional meaningful improvements. Include a safe, explicit opt-in/cost cap and record model/provider/token/usage. Do not claim to have called an API until a real call log exists.
3. Use real VLM as a **conditional observation tool** on Planner/Verifier-selected windows. Report frame/video evidence, uncertainties and suggested next search; do not turn a single-frame claim into FIRST LIVE truth.
4. Implement a **separate, guarded** candidate patch renderer and independent evaluation; compare candidate MP4/EDL against V3-R.
5. Implement at most 3 rounds with per-round acceptance/rollback; diagnose whether semantic quality truly improves instead of reporting only structural-score changes.

**Important:** The agreed design explicitly is **incremental model-driven story repair on top of V3-R**, not a full from-scratch remake, not a France-only goal-detector, not rule-only self-improvement, and not an LLM that rewrites verified story facts at will.
