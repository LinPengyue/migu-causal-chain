# STORY_VA_V2 G1 — A/B Transfer Comparison & G2 Readiness

## Freeze

- Pre-B code fingerprint: `/data2/lpy1/_story_va_outputs/v2/cross_match_g1/code_fingerprint_frozen_pre_b.txt`
- Source file SHA-256 unchanged across A→B (only absolute vs relative path listing differed in a later check; hashes identical).
- Zero code/threshold edits between frozen A refresh and B.

## Side-by-side

| Dimension | A 阿联酋–阿曼 | B 奥萨苏纳–塞尔塔 |
|-----------|---------------|-------------------|
| Gate | Gate1 structure PASS | Gate2 zero-mod transfer PASS |
| Protagonist | left / 阿联酋 | **right / 塞尔塔维戈** |
| Selected arc | 0:1→1:1→2:1 | **2:1→2:2→2:3** |
| Score path length | 4 states | 6 states |
| Unresolved missing goals | 3 | 5 |
| Video-verified goals | 0 | 0 |
| Predicted strips (reinfer) | 79 | 65 |
| EDL level | structure_only | structure_only |
| render_ready | false | false |
| API cost | 0 | 0 |
| Human causal/gold | none | none |
| Croatia cache reuse | none | none |
| Isolation keys | distinct video/events hashes | distinct |

## What transferred successfully (structure scope)

1. Explicit match identity + forbidden-input gates.  
2. Last-deficit arc selection (fixes G0 first-deficit left bias on B).  
3. Variable-N structure EDL without five-goal crash.  
4. Raw-events strip reinfer provenance (`reinfer_A_original`) without gold_clips dumps.  
5. Unresolved safety when no paid VLM.

## What did **not** transfer (must not overclaim)

- Live first-touch goal localization / shot–net binding.  
- Live-Only visual QC on rendered MP4.  
- Planner LLM quality under real API budget.  
- Formal long-form render deliverability.

## G2 preparation (recommended)

| Need | Why | Budget note |
|------|-----|-------------|
| Paid/local VLM goal verify windows from `missing_goal_candidates.search_region` | Promote `score_only` → `video_verified` | Per-match frame budget; track token/$ |
| Optional LLM planner on frozen graph | Narrative strip selection | Separate from vision |
| Generic EDL `video_verified` level + short candidate renders | QC loop | Still `render_ready=false` until human |
| Per-match empty source-corruption exception list | Do not copy Croatia 3:1 windows | — |
| Keep cache provenance mandatory | Prevent A/B/Croatia collisions | Already in G1 |

**G2 go condition (suggested):** A and B each obtain video-verified deficit/equalizer/go_ahead for the **selected_arc** with Live-Only pass on candidate clips — still not automatic `render_ready=true`.

**G1 verdict:** Structure dry-run **is** cross-match transferable for T01 under frozen code. Full V2 cross-match success is **not** declared.
