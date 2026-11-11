# V3-A Phase8: B/C full-cut zero-paid visual review

**Evidence:** user-supplied side-by-side MP4 comparisons `SIDE_V3R_THEN_B_2273_shot.mp4` (about 111.96s decoded container duration) and `SIDE_V3R_THEN_C_6400_defensive.mp4` (about 106.36s). User's original rendered cuts: V3-R 94.88s, B 112.11s, C 106.51s. Minor differences in container durations may arise from comparison rendering; use EDL and full-cut manifests for exact inserted media duration. Sampled frames at 0,8,...104 seconds were inspected across both panes; this is a visual screening, not a complete audio/video human-blind quality score. No paid HTTP.

## Results

- **Baseline V3-R:** retain as best available story. It progresses through early deficit, buildup and critical match outcomes without requiring filler solely because source PTS skips.
- **B (source 2273.20–2290.41, Shot, +17.23s):** the additional attacking sequence is more plausible as pressure buildup than the failed A save bridge, but it adds duration without a clearly identifiable necessary missing causal or game-state explanation in the completed cut. **Reject the current full-window insertion**; do not mark it `REVIEW_SUPPORTED` or a successful Agent revision. A different, much shorter independently validated sub-window is an untested hypothesis, not an accepted alternative.
- **C (source 6400.90–6412.50, Defensive, +11.63s):** defense/transition is not visibly a necessary cause or explanation for the later equalizer. It slows progression to the decisive result. **Reject the current insertion**.
- **A (3504 Save):** remains a prior negative control.

## Generalizable algorithm implications (no match-specific IDs in runtime)

1. Critic must identify *specific omitted story information*; a source-time jump is not a defect.
2. Search must distinguish relevance to a story role from a visually interesting independent highlight. Candidate shot/defense/heat/first-live are insufficient.
3. Planner must compare expected **marginal information gain versus marginal duration/pacing cost**, including before/candidate/after coherence and *baseline without insertion*. A positive triplet opinion is not enough to assert final-cut improvement.
4. The accepted default when no candidate demonstrably improves full-story comprehension is `KEEP`. If the defect is confirmed but no useful clip is observed, mark `UNRESOLVED`, not `REVISE`.
5. Any future model-driven acceptance should be evaluated on both baseline and candidate **full cuts** under matched context; reject padding/redundancy. First-live/source-provenance and no-replay constraints remain independent mandatory gates.
6. Do not hardcode 2273, 6400 or 3504 into the algorithm. Do not treat these judgments as a cross-match generalization result.

**Status:** B/C full-cut diagnostic variants not accepted; V3-R retained. This is a review of user-uploaded comparison media, not a source-frame cryptographic certificate and not a scored human-blind study.
