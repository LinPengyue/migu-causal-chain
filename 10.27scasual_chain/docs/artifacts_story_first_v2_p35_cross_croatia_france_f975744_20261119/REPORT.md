# Cross-match Story-First on f975744 — Croatia-Canada & France-Australia

`release_authorized=false`. First-live gates unchanged.

## 克罗地亚 vs 加拿大

| round | status | duration | note |
|---:|---|---:|---|
| 0 | V3_R | 131.440s | baseline kept |
| 1 | NOT_PRODUCED | — | Planner `interval_03:H4`; P2 `READY_FOR_TRIAL`; render refused `duplicate_canonical_role` `lead_extend_1_goal_action` |
| 2 | NOT_RUN | — | no accepted V1 |

Proposed windows (not delivered as preview): `5772.33–5788.33`, `5951.11–5967.11`, `6099.10–6115.10`, `6230.69–6246.69`.

## 法国 vs 澳大利亚

| round | status | duration | sha16 | P3 |
|---:|---|---:|---|---|
| 0 | V3_R | 135.953s | a7cdbf2b | — |
| 1 | ACCEPTED_PREVIEW | 182.742s | 9108ab19 | PLANNER_KEEP |
| 2 | ACCEPTED_PREVIEW | 203.407s | f38c9353 | PLANNER_KEEP |

- R1 pick `interval_01:H1`; P2 `READY_FOR_TRIAL`; windows `2563.19–2593.92` (`event_000084/85`), `2690.08–2706.08` (`event_000090`)
- R2 new window `2639.20–2659.83` (`event_000088/89`)
