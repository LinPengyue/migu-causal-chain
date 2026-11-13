# Stage3 B — new-key dual Qwen3.6/3.7 Step1

Both models completed real multimodal calls over **direct** Paratera (no HTTPS_PROXY). Prior blockers (3.6 HTTP 500; 3.7 proxy Tunnel 502) did not recur.

| model | http | real_ok | est$ | shot | net | live | team | struct_ready | verdict |
|-------|------|---------|------|------|-----|------|------|--------------|---------|
| Qwen3.6-Plus | 1 | 1 | 0.002881 | True | True | live | True | True | SOURCE_VIDEO_SEMANTIC_CONFIRMED_OBS |
| Qwen3.7-Plus | 2 | 2 | 0.007178 | True | True | live | True | True | SOURCE_VIDEO_SEMANTIC_CONFIRMED_OBS |

Gates remain locked: no EDL repair, no FIRST_LIVE. Observation-only.
Total est cost ≈ 0.0101 USD (provider estimate).
