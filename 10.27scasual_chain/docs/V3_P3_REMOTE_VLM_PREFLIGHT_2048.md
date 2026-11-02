# V3 Remote VLM — Effective Caps Preflight (zero HTTP)

**Baseline:** `074d9ec` (+ this commit)  
**Scope:** B opening_deficit **3132–3146** only  
**HTTP chat/completions:** **0**  
**render_ready / gate_opened / agent_auto_verified:** all false by design for first trial

---

## Effective config after trial overrides

Shell started from Phase4A env (keys present; not printed). Overrides applied in-process:

| Knob | Before (env file) | After (trial) |
|------|-------------------|---------------|
| `STORY_API_MAX_CALLS` | 3 | **3** |
| `STORY_API_MAX_COST_USD` | 0.10 | **0.5** |
| `STORY_API_MAX_COMPLETION_TOKENS` | 256 | **2048** |
| `STORY_VLM_MAX_COMPLETION_TOKENS` | unset | **2048** |
| `STORY_VLM_REQUEST_PROFILE` | unset | **video_rsi** |
| Flat thinking flags | unset | kept off |

**Vision request preview (no HTTP):**

- model: `Qwen3.6-Plus`
- `max_tokens`: **2048** (only token length field)
- `thinking`: `{"type":"disabled"}`
- `stream`: false
- temperature: 0.0
- does **not** send both token params / both thinking formats
- role effective output limit: **2048**
- TCP 443 to `llmapi.paratera.com`: OK
- `ready_for_real_when_approved`: **true**

Artifact: `_story_va_outputs/v3/plan2/p3_b_opening_vlm_verify/preflight_2048/api_config_audit_zero_http.json`

---

## Auto-verify hardening (code)

`cross_check_visible_evidence` now requires more than VLM `shot/net=true` + legal `frame_id`s:

1. **shot_sec ≤ net_sec** (PTS/requested media time)
2. times inside candidate window
3. **continuous accurate clip** confirmed
4. cited frame **files exist**
5. **LIVE only** (replay/unknown → gap)
6. score-order (not post `first_after`)
7. empty `uncertain` / continuous claim

Default **`observation_only=true`**: even a future real run keeps `agent_auto_verified=false`, does **not** open V2 Gate, `render_ready=false`.

---

## Next step (blocked until you approve budget)

```bash
# after explicit budget approval only
--enable-real-api --i-approve-budget \
--max-calls 3 --max-cost-usd 0.5 --max-completion-tokens 2048 \
--media-in 3132 --media-out 3146 \
# observation-only remains default
```

Still max **3 HTTP**, B opening window only — no other five goals.
