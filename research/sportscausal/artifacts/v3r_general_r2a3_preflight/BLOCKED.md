# V3-R-General R2a.3 preflight — BLOCKED

- Target HEAD: `98d1fb1822ccde6b60a1f98dfa78bc50f1e8aa25` (worktree checked out)
- Baseline compare: `3d90a20`
- Paid HTTP: none

## Blocker 1 — missing attachment `V3R_General_R2a3_patch.zip`

Searched under `/data2/lpy1`, `/home/lpy1`, `/tmp`, Cursor project/agent-tools/stores, and recent `*.zip` (mtime−7). **File not present on this host.**

At HEAD, only **2** R2a3-related stubs exist and are **not wired** into any runner:

| file | status |
|---|---|
| `episode_goal_binding.py` | present (b171edc) |
| `episode_relation_evidence.py` | present (98d1fb1) |
| `r2a3_patterns.py` | **missing** |
| `test_event_relation_graph.py` | **missing** |
| `event_relation_graph.py` (expected by audit outputs `relation_graph.json`) | **missing** |
| updates to `causal_episodes.py` / related | **not in HEAD vs 3d90a20** (only the 2 new files) |

User instruction: unzip patch and confirm **exactly 6** research/sportscausal code files added/modified. Cannot invent those modules; algorithm ownership is ChatGPT/author.

Therefore **not run**:

```
python -m unittest -v test_v3r_general test_causal_episodes test_event_relation_graph
python r2a3_patterns.py ...
```

## Blocker 2 — score_side_mapping not verified (secondary once patch arrives)

Historical **score_path** bodies were located (not fabricated):

- A/B T01: `.../reports/story_t01/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json`
- A/B T01: `.../reports/story_t01/10月27日_25-26赛季西甲第10轮_奥萨苏纳VS塞尔塔_国语.json`

Copied to `inputs_prepared/{A,B}_score_path_from_t01.json` with:

- `video_id` aligned to Stage 1.2 evidence
- full `score_path` (A: 4 nodes 0:0→2:1; B: 6 nodes 0:0→2:3)
- `score_side_mapping: null` — T01 artifacts do **not** record left/right→team_1/team_2; empty Goal notes near transitions do not independently prove board orientation. Per instructions, mapping must be verified, not assumed as left=team_1.

R2a.2 `normalized_semantics.json` and Stage 1.2 full `evidence.json` are already on branch and reusable.

## Next action required from GPT/user

1. Provide `V3R_General_R2a3_patch.zip` on this machine (or push the 6 files to the research branch).
2. Provide verified `score_side_mapping` for A and B (or point to the historical JSON that already contains it).

Then re-run the same R2a.3 protocol without re-executing old experiments.
