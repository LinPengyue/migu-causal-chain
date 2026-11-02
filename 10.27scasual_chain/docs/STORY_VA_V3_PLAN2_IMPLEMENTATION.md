# Story Video Agent V3 — Plan 2 / Implementation & Handoff

**Date:** 2026-11-02  
**Branch:** `story-va-v3-plan2` (branched from `story-va-video-driven` at `2a17db72b613d7e1f47d835ba1902d5c93286ad9`)  
**V1 / V2 / 8.31:** **frozen; no changes to existing modules or artifacts**.  
**Scope:** T01 (逆风翻盘), A=UAE–Oman, B=Osasuna–Celta.  
**No API calls, no model training, no render, no automatic verified or production delivery.**

## 1. Decision & implementation map

```
8.31 causal_chain6 predicted strips (read-only frozen output)
    -> story_video_agent_v3.pipeline.to_predicted_causal
       (V1-shaped causal_chains, provenance + source IDs + confidence)
    -> V1 narrative_composer.compose_story_plan (read-only)
       V1 phase5_delivery: build_story_scope, select_delivery_rows, build_story_graph
    -> V3 candidate_edl with three explicit unresolved goal placeholders
    -> V3 critical_goal_evidence_tasks.json
    -> V3 gate.py -> existing V2 v2_video_evidence_gate (read-only)
    -> verified_candidate_edl.json IF evidence is real and passes; still render_ready=false
```

V3 uses **V2 last-deficit arc** to select the protagonist/score trajectory (A left, B right last arc) and feeds it to V1's planner. This is intentionally **not** V1's old first-deficit recognizer as-is. The original predicted causal chains are saved in `predicted_causal.json`. The **safe V1 planner view** excludes predicted Goal chains: V1's old `merge_causal_live_goals` expects truth-like goal action timestamps, which 8.31 predictions do not supply. Non-goal predicted strip events can be editorial buildup candidates; their status remains unverified.

V3 never treats a score-confirmation PTS as a goal-action PTS. Goal placeholders are explicitly present in V3 candidate EDL even if V1's ordinary delivery selector would drop missing footage. Scoreboard segments are labeled scoreboard-only, not goal evidence; no media is rendered by the V3 structural stage.

## 2. Files added (all V3-only)

- `algo/story_video_agent_v3/pipeline.py` — raw event/strip input guards; predicted_causal V1 field projection; last-deficit arc; read-only V1 planner+scope+graph+EDL; placeholder/evidence task creation.
- `algo/story_video_agent_v3/gate.py` — role-indexed verification gate. Requires first LIVE, observed shot and net, attacking team match, no replay/stitch, continuity and V2 identity bound media; separate human/automated verification.
- `algo/story_video_agent_v3/__main__.py`, `__init__.py`
- `algo/story_video_agent_v3/test_pipeline.py` — synthetic A/B regression (actual A/B results are NOT claimed).
- This document.

No existing V1/V2 paths were modified; all outputs must be under a dedicated path component `v3/` and a fresh run directory. Nonempty output is refused.

## 3. Existing frozen A/B inputs and first-pass commands

```bash
cd /tmp/migu-va2c
export PYTHONPATH="$PWD/10.27scasual_chain/algo"
```

### A — left / UAE last deficit

```bash
python3 -m story_video_agent_v3 \
  --match-id '10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语' \
  --events '10.27scasual_chain/data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json' \
  --video '/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4' \
  --predicted-strips '/data2/lpy1/_story_va_outputs/v2/cross_match_g1/A_uae_oman/strip_reinfer/strip_A_original.json' \
  --out-dir '/data2/lpy1/_story_va_outputs/v3/plan2/A_uae_oman_run01'
```

### B — right / Celta last deficit

```bash
python3 -m story_video_agent_v3 \
  --match-id '10月27日_25-26赛季西甲第10轮_奥萨苏纳VS塞尔塔_国语' \
  --events '10.27scasual_chain/data/交付_out/10月27日_25-26赛季西甲第10轮_奥萨苏纳VS塞尔塔_国语.json' \
  --video '/mnt/data4/migu/10月27日 25-26赛季西甲第10轮 奥萨苏纳VS塞尔塔 国语.mp4' \
  --predicted-strips '/data2/lpy1/_story_va_outputs/v2/cross_match_g1/B_osasuna_celta/strip_reinfer/strip_A_original.json' \
  --out-dir '/data2/lpy1/_story_va_outputs/v3/plan2/B_osasuna_celta_run01'
```

Confirm local file paths first; these are prior G1 server paths, **not files reachable from this GitHub session**. If the frozen strip file is absent, **STOP** rather than rerun 8.31 or substitute gold. Before running, check the expected 79/65 are actually present (code reports `n_predictions`); 79/65 are previous G1 facts, **not yet revalidated by V3**. Run on a separate V3 working tree / checkout, NOT by switching a dirty V1/V2 worktree.

## 4. Outputs & acceptance

Each successful dry run writes:

```
predicted_causal.json
selected_arc.json
story_view.json
story_plan.json
story_graph.json
candidate_edl.json
critical_goal_evidence_tasks.json
provenance.json
run_report.json
```

Acceptance should check **all**:

1. A `n_predictions=79`, B `n_predictions=65`, `n_dropped=0`, `prediction_source=causal_chain6_predicted`, input SHA256 present.
2. A protagonist left / UAE with score arc 0:1→1:1→2:1; B protagonist right / Celta with **last** arc 2:1→2:2→2:3. Preserve full score history to distinguish B's earlier left-side comeback.
3. V1 `story_plan.json`, `story_graph.json` and EDL can be built; `structure_ok=true` or report exactly which link/segment fails. Story completeness must be audited separately from whether the program runs.
4. Three critical goal slots exist, with `media_in=null`, `media_out=null`, `goal_action_sec=null`, `verification_status=unresolved`. Scoreboard time is only `score_confirmation_sec`.
5. Predictions carry confidence, event IDs, PTS in milliseconds, hashes and source; **no fabricated Goal, verified status or causal edges**.
6. No API calls, no MP4 export, `render_ready=false`, V1/V2/Croatia R2.9 and independent 8.31 remain unchanged.
7. Compute per-match meaningful buildup candidate recall / relevance manually. **Zero candidate buildup** should not be interpreted as structure fully good; identify missing predicted result chains explicitly.

## 5. V2 critical-video verification handoff (after first-pass acceptance)

Only seek 3 critical action slots per match, **not** an unbounded whole-game G2.4 search. Provide evidence as:

```json
{
  "goals": [
    {
      "role": "equalizer",
      "identity": {
        "match_id": "<exact match id>",
        "video_sha256": "<V3 provenance hash>",
        "events_sha256": "<V3 provenance hash>",
        "strip_provenance": "<V3 provenance input_hashes.strips_sha256>"
      },
      "live_or_replay": "live",
      "observed_shot": true,
      "observed_net": true,
      "first_live_visual_ok": true,
      "attacking_team_match": true,
      "claims_continuous_live": true,
      "media_in": 0.0,
      "shot_sec": 0.0,
      "net_sec": 0.0,
      "media_out": 0.0,
      "clip_path": "/absolute/path/continuous_live_clip.mp4",
      "frame_paths": ["/absolute/path/shot.jpg", "/absolute/path/net.jpg"],
      "semantic_verification_class": "automated_video_verified",
      "automated_semantic_log_path": "/absolute/path/auto_semantic_log.json"
    }
  ]
}
```

Times above are **schema placeholders only**, not measured data. `first_live_visual_ok`, `observed_shot` and `observed_net` must be established by actual contiguous video evidence. Human-only review is an independent class and requires `--allow-human-reviewed`; never count it as autonomous agent success.

```bash
python3 -m story_video_agent_v3.gate \
  --v3-run-dir '/data2/lpy1/_story_va_outputs/v3/plan2/A_uae_oman_run01' \
  --evidence-pack '/path/to/actual_evidence_pack.json' \
  --out-dir '/data2/lpy1/_story_va_outputs/v3/plan2/A_uae_oman_review01'
```

Even three passing roles only yield `candidate_for_visual_qc`; `render_ready=false`. Formal candidate video rendering requires a **separate** implementation & visual source corruption QC; V3 currently does **not** implement render/publish. Existing Croatia 3:1 first-LIVE source corruption must never be silently overridden.

## 6. Tests and remaining STOPs

```bash
PYTHONPATH=10.27scasual_chain/algo \
  python3 -m unittest story_video_agent_v3.test_pipeline -v
```

At authoring time these tests were committed but **could not be executed against the private server MP4s / existing G1 artifact files from this session**. Cursor/server should run tests before treating any pass as confirmed. If V1 planner cannot produce a usable T01 graph from predicted context, first evaluate predicted result-chain recall, not another whole-match video search.

### Non-negotiable isolation

- Never edit `story_chain`, `story_video_agent` (V1/V2), `8.31causal_chain` or legacy output folders for V3.
- Never merge V3 work directly into V1/V2 branch. Review this branch independently.
- Use V3-specific paths, explicit match IDs and input hashes.
- Never use `*_causal.json`, `gold_clips`, curated causal truth or legacy Croatia cache as model input.
- No API charges, no silent background run.
