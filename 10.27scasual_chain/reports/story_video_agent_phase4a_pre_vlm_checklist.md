# Phase 4A / 4A.1 真实 VLM-only 联调前检查清单（无计费）

**分支**: `story-va-phase2c` · **未执行付费 API** · **未合并 main**

## 已修复（含 4A.1）

1. **HTTP 限额合并**：`min(代码显式, 环境变量)`；默认 12 不覆盖 `STORY_API_MAX_CALLS=3`。
2. **HTTP 计数测试**：成功 / 400 / 429 均计入；第 4 次 `budget_exhausted`。
3. **dry-check**：生效 caps、官方双模型标签 vs `request_models`、端点/密钥布尔、token_param；**无 Key 明文**；`--real --dry-check` 不发 HTTP。
4. **语义签发澄清**：`attest_semantic_result(passed)` ≠ 视觉事实核验；模型 goal 不能成片。
5. **持久密钥 + content_sha256** 媒体身份。
6. **`--targets`**：`equalizer_goal` / `go_ahead_goal` / 两者；默认两者兼容；首次真实仅 equalizer @3065.903s。
7. **首次联调固定**：max_rounds=1、frames_per_round=2、frame_budget=4、HTTP≤3、completion_tokens≤256；费用仅为估算。

## 门禁保持

- go_ahead unresolved（首次不搜 go_ahead）
- `render_ready=false`
- `final` 硬拒绝
- Mock 不能绕过授权

## Video-RSI 官方模型

- Planner: `deepseek-v4-pro`
- VLM: `qwen3.6-plus`
- 实际 `request_model` = 服务商可用 ID（`STORY_LLM_MODEL` / `STORY_VLM_MODEL`）

## Dry-check 产物

- Mock 预检：`reports/phase4a_vlm_only_drycheck.json`
- 真实模式预检（无 HTTP）：`reports/phase4a_vlm_only_real_drycheck.json`

下一步：用户明确授权 + 配置 Key 后，按 `phase4a_vlm_only_playbook.md` 手工执行 `--real`（勿自动跑）。
