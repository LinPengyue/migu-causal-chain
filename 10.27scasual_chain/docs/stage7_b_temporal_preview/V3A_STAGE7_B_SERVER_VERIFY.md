# Stage7 B — server verify (zero HTTP)

Code: `ad83e7f`. Pytest: **9 passed**. No paid API.

## `temporal_broadcast_diagnostics.json`

- status: **BROADCAST_CUT_CANDIDATES_ONLY**
- window: [6422.2, 6475.6]  step=0.5s
- shot/net: [6447.2, 6450.6]
- decoded: 107/107 (coverage=1.0)
- cut_candidates: **4** (all after net; none during shot→net)
  - [(6451.7, 6452.2), (6454.2, 6454.7), (6456.7, 6457.2), (6461.7, 6462.2)]
- first_live_verified: **false**, edl_repaired: **false**

## Gate

Cut diagnostics ≠ live/replay classifier ≠ FIRST_LIVE. No EDL repair.
Next: segment same-action match + broadcast-phase labels + hard negatives.

Out: `/tmp/lpy1_v3a_stage7_B_temporal_20261113`
