# STORY_VA_V2 G0 — Proposed Generic Interface Contract (design only)

**Status:** Design for G1+. **Does not change** current production CLI defaults or R2.x outputs in this commit beyond optional isolation helpers.

## 1. CLI (proposed)

```text
v2_strip_guided_cross_match_cli.py   # name TBD — or flags on r2_3_cli
  --match-id TEXT                 # required
  --video PATH                    # required
  --events PATH                   # required; basename must not be *_causal.json / *gold*
  --input-source {human_corrected,upstream_detected}
  --algo-root PATH                # 8.31 predicted strip runner root
  --strip-run-id TEXT             # becomes strip_provenance
  --r22-dir PATH                  # required for reuse; NO Croatia default when match_id≠croatia
  --reuse-verify-cache PATH       # optional; must pass provenance gate
  --out-dir PATH
  --real / --max-api-calls ...    # unchanged budget knobs; G0 used none
```

**Hard refusals**

- Missing `--match-id` / `--video` / `--events`.
- Events path basename ∈ `{strip_gold.json, highlight_gold*.json}` or ends with `_causal.json`.
- Payload top-keys ∈ `{causal_chains, causal, story_graph, story_plan, story_roles, strip_gold, edges}`.
- `--reuse-verify-cache` entry lacking or mismatching provenance → reject (no Croatia fallback).

## 2. Cache isolation key

```text
cache_key = sha256(match_id | video_sha256 | events_sha256 | strip_provenance)
```

Each `verify_{event_id}/` and strip cache dir must embed a `provenance.json`:

```json
{
  "match_id": "...",
  "video_sha256": "...",
  "events_sha256": "...",
  "strip_provenance": "algo_predicted:<run_id>",
  "schema": "v2_cache_provenance_v1"
}
```

G0 helper: `v2_g0_cross_match_preflight.assert_cache_binding`.

## 3. T01 narrative roles (variable N; not fixed five)

Roles describe **function**, not a requirement that `len(goals)==5`:

| Role | Meaning |
|------|---------|
| `opening_deficit` | First (or selected arc) trail for protagonist |
| `equalizer` | Level after deficit |
| `go_ahead` | Lead after equalizer |
| `extend_or_context_*` | Optional further goals / setup strips |
| `no_comeback` | Do not fabricate T01; status only |

Selection rule for multi-arc boards (B): **`last_deficit_arc`** — last time protagonist trails, then levels, then leads before final whistle window.

Statuses: `unresolved` | `no_comeback` | `partial_story` | `story_candidate` (never auto-`render_ready`).

## 4. Verification states

```text
missing_goal_candidate → search → verify_frames →
  verified_first_live | unresolved | rejected_replay_or_ambiguous
```

- Score confirmation time ≠ action time.
- No cross-probe stitch of shot+net.
- 8.31 lacking `outcome` does not alone negate a video-verified goal.
- Unresolved critical goal → story may be `partial` / blocked deliverability; **no invented verified**.

## 5. EDL / deliverability gates

Generic EDL segment schema (conceptual):

```json
{
  "segment_id": "edl_goal_<k>",
  "role": "equalizer",
  "media_in": 0.0,
  "media_out": 0.0,
  "score_before": [1,1],
  "score_after": [2,1],
  "source_node_ids": ["ke_..."],
  "live_only_ok": true
}
```

Gates (unchanged philosophy):

- `render_ready=false` until human review.
- `visual_qc_pass` independent.
- `blocked_source_corruption` is **per-window / per-match**, never imported from Croatia R2.9 list.
- Live-Only: REPLAY / ambiguous → conservative exclude.

## 6. Outputs (per match run)

- `cli_report.json`, `story_graph.json`, `story_summary.md`
- `candidate_edl.json` (generic)
- `provenance.json` (inputs + hashes)
- `visual_qc_report.json` if rendered
- Never write gold/causal into out_dir as “inputs used”

## 7. Compatibility

- Keep `v2_strip_guided_r2_{6,8,9}_build_edl.py` as **Croatia-tagged** modules.
- New generic composer lives beside them; G1 wires A/B only to generic path.
