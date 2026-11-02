# V3-P3 Remote VLM Verify — Wiring & Zero-Cost Preflight

**Baseline:** `6d4e01f`  
**Branch:** `story-va-v3-plan2`  
**Focus:** B `opening_deficit` candidate **3132–3146s**  
**This turn:** code + mock + **zero-HTTP** config audit only. **No billed chat/completions.**  
**render_ready:** `false`

---

## Headline

V3 now reuses V2 `ApiProvider` / `VisionProvider` / frame PTS binding for remote multimodal verification.  
Mock path on B opening stays `possible_first_live` / `unresolved` (`agent_auto_verified=false`).  
Real Qwen3.6-Plus calls are **gated** until you approve budget (`--enable-real-api` **and** `--i-approve-budget`).

---

## 1. V2 reuse (read-only)

| V2 module | Use in V3 |
|-----------|-----------|
| `api_provider.py` | `ApiProvider`, caps, `vision_json`, output-budget block |
| `vision_provider.py` | `normalize_evidence`, frame_id binding, failure taxonomy |
| `frames.py` + `media.probe_video` | Dense extract with `actual_media_sec` / `pts_status` |
| `v2_phase_c1_toolbox` patterns | Dense inspect span caps / multi-round densify (logic mirrored, not patched) |
| `v2_api_preflight` | **Not** invoked this turn (HTTP probes can bill); replaced by zero-HTTP `scrub_config_audit` |

**V2 code untouched.**

New V3 files:

- `story_video_agent_v3/remote_vlm_verify.py`
- `story_video_agent_v3/vlm_verify_cli.py`
- `story_video_agent_v3/test_remote_vlm_verify.py`

---

## 2. Zero-HTTP config audit (no secrets)

Env sourced from gitignored Phase4A file (path only; key never printed).

| Check | Result |
|-------|--------|
| Vision model | `Qwen3.6-Plus` |
| Planner model | `DeepSeek-V4-Pro-0813` |
| Base URL | `https://llmapi.paratera.com/v1` |
| API key set | planner=yes, vision=yes |
| `STORY_API_ENABLE` | unset → real path not armed |
| TCP 443 to host | OK (`llmapi.paratera.com`) |
| HTTP chat/completions sent | **0** |
| `ready_for_real_when_approved` | **true** |

**Cap warning:** env currently applies `STORY_API_MAX_COMPLETION_TOKENS=256` (and `MAX_CALLS=3`, `MAX_COST_USD=0.10`) via min(explicit, env).  
256 is **too tight** for structured goal-verify JSON (historical truncate / empty_json risk). For the first real trial, recommend temporarily raising vision completion budget to **≥2048** (or unset the env cap) while keeping **max_calls=3** and **thinking disabled** (`STORY_VLM_REQUEST_PROFILE=video_rsi`).

Artifact:  
`_story_va_outputs/v3/plan2/p3_b_opening_vlm_verify/config_audit/api_config_audit_zero_http.json`

---

## 3. Mock verify on B 3132–3146

```text
provider_mode=mock
http_attempts=0
agent_auto_verified=false
verification_status=unresolved
semantic_label=possible_first_live
output_budget_exceeded=false
```

Pipeline exercised:

1. Round1 dense frames inside candidate (≤12s focus) with PTS bindings  
2. Round2 adaptive densify (net unclear) still **inside** 3132–3146 — no full-match expand  
3. VLM inference vs visible cross-check stored separately  
4. High confidence / mock “进球了” **cannot** auto-upgrade to `verified_first_live`  
5. `automated_semantic_log.json` written fail-closed  

Artifact root:  
`_story_va_outputs/v3/plan2/p3_b_opening_vlm_verify/mock_run/`

---

## 4. Suggested first real-API budget (await your approval)

| Parameter | Suggestion |
|-----------|------------|
| HTTP calls | **≤3** (R1 dense + R2 densify + optional live/replay; stop on output_budget_exceeded) |
| Model | `Qwen3.6-Plus` (existing) |
| Thinking | **off** (`video_rsi` / thinking disabled) |
| `max_completion_tokens` | **2048** (override env 256 for this trial) |
| Soft cost estimate cap | **$0.50** (or keep env `$0.10` if preferred — may stop early) |
| Enable flags | `--enable-real-api --i-approve-budget` |
| Scope | **Only** B opening 3132–3146 (no A/B five-goal expansion) |

Example (do **not** run until approved):

```bash
set -a; source /path/to/phase4a_paratera.env; set +a
# ensure STORY_API_MAX_COMPLETION_TOKENS>=2048 for this shell
PYTHONPATH=... python3 -m story_video_agent_v3.vlm_verify_cli \
  --video '...' --media-in 3132 --media-out 3146 \
  --out-dir .../real_trial_01 \
  --score-bounds-json .../score_bounds.json \
  --max-calls 3 --max-completion-tokens 2048 --max-cost-usd 0.5 \
  --enable-real-api --i-approve-budget
```

After any reported `completion_tokens` over the configured output budget, `ApiProvider` **blocks further real HTTP** (`failure_status=output_budget_exceeded`).

---

## 5. Evidence gaps real VLM is expected to address

| Gap from P3 localization | How remote VLM helps |
|--------------------------|----------------------|
| LIVE 广角 `observed_net` 难证 | Cite `net_frame_ids` with PTS; if still unclear → densify R2, else stay unresolved |
| Shot vs celebration | Separate `observed_shot` / celebration-only |
| LIVE vs later ~3175 replay | `live_or_replay` on first-live window only |
| Attacking side vs 1:1→2:1 | `attacking_team_match` + notes vs score delta |
| Event sparsity / OCR fail | VLM does not replace score bounds; cross-check still required |

Still **not** enough alone: model saying “goal” without cited frames + empty `uncertain` + score-order OK + `provider_mode=real` → Gate stays closed.

---

## 6. Tests

```text
unittest story_video_agent_v3.test_remote_vlm_verify (+ first_live_localize)
→ OK (budget gate, cross-check, zero-HTTP audit shape)
```

---

## 7. Freeze / non-goals this turn

- No paid HTTP  
- No V1/V2/8.31 edits or product overwrites  
- No expansion to remaining five goals  
- No auto render (`render_ready=false`)
