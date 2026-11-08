# Phase 8 — Third-audit real-loop gate response

Review input: `docs/PHASE8_THIRD_AUDIT_CLOSEOUT_AND_REAL_LOOP_GATE.md`  
Branch: `story-va-v3a-phase8-loop-impl`  
Zero HTTP. No V1/V2. No gold. No Phase 9. No paid calls.

## Fixes

| Gate | Change |
|---|---|
| Real first-LIVE | New `first_live_window_evidence.py`: local source-MP4 frame packs with content SHA + manifest digest. Ledger rejects event-chain labels and raw `targeted_visual_verified` booleans. EDL-diff binds newly introduced windows (not apply_report alone). Validated evidence required for PASS. |
| Paired ablation | Same baseline EDL + events + diagnosis; with-feedback suppresses A→B; no-feedback keeps A. A still in `verified_candidates_before_feedback` (occupancy confound excluded). |
| Evidence token | Observation-grade only with frame-*byte* hashes and/or manifest digest. Round/version ids and plain `baseline_a` frame_ids no longer unlock retries. |

## Tests

```bash
PYTHONPATH=algo python -u -m pytest \
  tests/test_v3a_phase8_*.py \
  tests/test_v3a_phase7_semantic_evidence.py \
  tests/test_v3a_phase6_semantic.py \
  tests/test_v3a_story_e2e.py -q --tb=line -k 'not cross_match'
```

**77 passed, 1 deselected.** Cross_match / unmocked unified E2E NOT RUN.

## Proof artifacts

`docs/phase8_review_artifacts/third_audit_proof/`

| Artifact | Result |
|---|---|
| `first_live_negative.json` | Event-chain + boolean → safety **UNKNOWN** |
| `first_live_positive.json` | Local source frame-pack → ledger **FIRST_LIVE_VERIFIED**, hard safety **PASS** (with candidate mp4) |
| `paired_ablation.json` | Same EDL: no-fb top=A@896; with-fb filtered=[A], top=B@1496; `before_feedback_still_has_A=true` |
| `positive_pack/` | Extracted frames + `evidence.json` / `manifest.json` with content hashes |

## Still unresolved

- Formal release-grade “first broadcast LIVE across full timeline” remains stricter than local frame-pack binding
- Paid VLM multi-round quality gain / unseen-match generalization **UNVERIFIED**
- No Phase 9
