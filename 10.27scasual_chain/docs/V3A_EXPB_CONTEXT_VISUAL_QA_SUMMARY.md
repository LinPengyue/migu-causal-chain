# ExpB Context Visual QA — server verify (zero HTTP)

- Branch: `story-va-v3a-p17-native-broadcast-observer`
- HEAD tested: `aa5f357`
- Paid HTTP: **0**

## Pytest

```
...............................................                          [100%]
47 passed in 0.67s
```

**47 passed** (`test_v3a_expb_context_visual_qa` + native observer + continuous broadcast phase).

## Preflight

- Status: **`READY_ZERO_HTTP_PREFLIGHT`**
- `n_real_http_calls=0`, `first_live_verified=false`, `edl_modified=false`
- Issue: `goal_coverage_01_to_11`
- Anchors (revalidated Stage3): shot **6447.88** / net **6450.6**
- Source SHA: `a66147f79609c8fb…` match
- Image frames: **13** (cap zones: pre=4, action=3, post=6)
- Total image bytes: **2789120** / 10485760
- max |requested−actual| PTS: **0.020000000000436557**; all `pts_status=pts`
- Blocked reason: **null**

## Paid call

**Not executed** (awaits separate authorization). Preflight itself has no code blocker.

JPEG frames remain local under `/tmp/lpy1_v3a_expb_context_visual_qa_preflight_20261113/` (not committed).
