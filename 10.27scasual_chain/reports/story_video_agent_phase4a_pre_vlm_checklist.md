# Phase 4A 真实 VLM-only 联调前检查清单（无计费）

**分支**: `story-va-phase2c` · **未执行付费 API** · **未合并 main**

## 已修复

1. **HTTP 限额合并**：`ApiProvider` / Phase4A 对 `max_calls`、`max_cost_usd`、`max_completion_tokens` 取 `min(代码显式, 环境变量)`。默认 `max_api_calls=12` 不再覆盖 `STORY_API_MAX_CALLS=3`。
2. **HTTP 计数测试**：成功 / 400 / 429 均计入；`MAX_CALLS=3` 时第 4 次 `budget_exhausted`（`test_phase4a_caps.py`）。
3. **dry-check**：输出生效 caps、模型名、token_param / retries / timeout、`api_key_set` 布尔；**无 Key 明文**（见 `reports/phase4a_vlm_only_drycheck.json`）。
4. **语义签发澄清**：`attest_semantic_result(passed)` ≠ 视觉事实核验；生产仅接受 `human_audited_review` / `independent_verification_pipeline`；模型 goal 标签 → `observation_only`，不能成片。
5. **持久密钥**：无 `STORY_INTERNAL_VERIFY_KEY` 时拒绝生产 promote；媒体指纹含 `content_sha256`（head/mid/tail 采样）。
6. **联调方案**：`reports/phase4a_vlm_only_playbook.md`（不自动跑实验）。

## 门禁保持

- go_ahead unresolved  
- `render_ready=false`  
- `final` 硬拒绝  
- Mock 不能绕过授权  

## Dry-check 摘要（本机）

| 项 | 生效值 |
|----|--------|
| max_calls | **3**（env；显式 12 → min=3） |
| max_cost_usd | **0.08** |
| max_completion_tokens | **128** |
| token_param | max_tokens |
| verify_key_persistent | false |
| billing_allowed | false |

下一步：用户明确授权 + 配置 Key 后，按 playbook 手工执行 `--real` VLM-only。
