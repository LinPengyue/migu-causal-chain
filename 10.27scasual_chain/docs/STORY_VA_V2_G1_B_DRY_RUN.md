# STORY_VA_V2 G1 — Match B Dry Run（奥萨苏纳 vs 塞尔塔）

**Status:** `ok_structure_dry_run` (Gate 2 PASS for zero-modification structure transfer)  
**Code freeze:** same source hashes as pre-B fingerprint (`code_fingerprint_frozen_pre_b.txt`); only A/B input paths changed.  
**Not claimed:** video-verified goals or delivered MP4.

## Inputs (absolute)

| Item | Path |
|------|------|
| MP4 | `/mnt/data4/migu/10月27日 25-26赛季西甲第10轮 奥萨苏纳VS塞尔塔 国语.mp4` |
| Events (raw) | `/tmp/migu-va2c/10.27scasual_chain/data/交付_out/10月27日_25-26赛季西甲第10轮_奥萨苏纳VS塞尔塔_国语.json` |
| match_id | `10月27日_25-26赛季西甲第10轮_奥萨苏纳VS塞尔塔_国语` |
| Algo root | `/data2/lpy1/causal-chain2/8.31causal_chain` (readonly) |
| Out dir | `/data2/lpy1/_story_va_outputs/v2/cross_match_g1/B_osasuna_celta/` |

**Forbidden:** causal/gold/Croatia cache/Phase5 — none used.

## Provenance

| Field | Value |
|-------|-------|
| video_sha256 | `0d422f60e2999cc200d5…` (**≠ A**) |
| events_sha256 | `e75c2ad5e394d0e87db0…` (**≠ A**) |
| cache_isolation_key | distinct from A |
| strip mode | `reinfer_A_original` · **65** chains |
| api | **0** |

## Results — last right-side arc

| Check | Result |
|-------|--------|
| score_path | `(0,0)→(0,1)→(1,1)→(2,1)→(2,2)→(2,3)` |
| selected_arc | **right / 塞尔塔维戈** · `[2,1]` @3199.66 → `[2,2]` @5712.01 → `[2,3]` @6881.94 |
| Abandoned complete other arc | **left** go_ahead `[2,1]` (first comeback) — correctly **not** selected |
| unresolved missing goals | **5** (`verification_status=unresolved`) |
| video_verified | **0** |
| EDL | structure_only placeholders; `render_ready=false` |
| croatia EDL | refused |
| elapsed | ~26s |

## Zero-modification transfer

CLI flags identical to A except `--match-id`, `--video`, `--events`, `--out-dir`. No threshold/rule edits between A refresh and B.
