# Croatia H4 split-goal render resume (`b5d782d`)

## Verdict
- **V1 rendered** and **entered P3** (`preview_accepted=true`, `stop_reason=PLANNER_KEEP`).
- **3:1 approach + result both kept**; **0.9s glitch gap 6315.8–6316.7 not in cut** (`glitch_gap_overlap_sec=0`).
- Outer continued to **2 accepted changes**; `release_authorized=false`.
- Paid usage: **9 HTTP / ~$0.0225** (cap 16 / $0.05).

## Code / inputs
- Branch: `fix/story-first-split-goal-render` @ `b5d782d`
- Reused prior P2 trial: `/tmp/story_first_outer_croatia_canada_20261119_234432` (`interval_03:H4`, `READY_FOR_TRIAL`)
- Source: `/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4`

## 3:1 windows (V1 / P3 selected)
| segment | media_in | media_out |
|---|---|---|
| `seg_lead_extend_1_goal_action_approach` | 6305.199 | 6315.8 |
| `seg_lead_extend_1_goal_action` | 6316.7 | 6327.199 |
| *(excluded glitch)* | 6315.8 | 6316.7 |

## Videos (local, not in git)
See `VIDEO_PATHS.txt`.

## Notes
- No quality claim; preview-only; `release_authorized=false`.
