# Phase 4D — 动态搜索种子接入

## 行为

- 默认 `--seed-mode story` → `seed_targets_from_story(story, causal)`
- preflight 与 `run_phase4a` **同一** `resolve_seed_targets`；不一致则硬失败
- `--seed-mode croatia_legacy` 仅显式兼容测试
- 禁止 `seed_center == score_anchor`（±1s）

## CLI

```text
--causal-json PATH
--seed-mode {story,croatia_legacy}
```

## 回归（无计费）

- 法国 vs 澳大利亚：种子落在法澳 board（≈2513 / 2904），非克罗地亚硬编码
- 合成/真实无翻盘：`seed_targets_from_story` 抛错，不把比分牌当进球动作
- `test_phase4d_seed_wiring.py` + 既有 caps/4C 测试通过
