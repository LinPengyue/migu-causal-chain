# P3.5 outer — Osasuna vs Celta (ed72bce)

`release_authorized=false`. Outer 0/1/2 compare **did not materialize** beyond V0.

## Result

| outer_rounds | status | duration | note |
|---:|---|---:|---|
| 0 | V3_R baseline | see VIDEO_PATHS | only available preview |
| 1 | blocked | — | P2 `NEEDS_REVISION` / replay overlap on sub window |
| 2 | not run | — | needs accepted round-1 preview |

## Round-1 proposed windows (not applied)

See `P35_OUTER_OSASUNA_CELTA_SUMMARY.json` → `proposed_source_windows_sec`.

Blocked window: events `event_000534`,`event_000536` overlapped replay/slowmo `event_000532`,`event_000533`.

## UAE Caption (A match round-2)

Packaged under `uae_caption_round2/p3/round_01/`. HTTP 1× OK (`Qwen3.7-Plus`), but binder dropped all 3 observations (`clip_id`/`story_range_sec` mismatch) → `CAPTION_UNAVAILABLE`.
