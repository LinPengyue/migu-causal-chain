# Story Video Agent Phase 3A — Story Verifier + Narrative Composer

## Verdict
规则基线可从 T01 + score_path +（可选）视觉证据生成咪咕剪辑故事线方案（Story JSON / EDL / 五段报告）。**Mock 视觉不得当真实事实**；回放仅 `replay_supplement`；`none` 不强制翻盘。本阶段**未**跑付费 LLM。

## Modules
| 文件 | 作用 |
|------|------|
| `story_output_schema.py` | schema / EDL / 报告 / 结构校验 |
| `story_verifier.py` | 比分、归属、回放、视觉证据分类与冲突 |
| `narrative_composer.py` | 铺垫→蓄力→转折→高潮→收尾编排；可选 LLM 仅润色文案 |
| CLI `--compose` | 无计费规则输出 |

## Evidence kinds
`rule_fact` · `vlm_observation` · `verified` · `mock` · `unresolved_conflict`  
→ `mock.used_as_fact` 永远为 false。

## Tier 行为
- **story**：完整候选编排（法国示例）
- **candidate**：不完整 + `missing_evidence`（克罗地亚示例）
- **none**：`blocked_none`，无翻盘 segments

## API 兼容
`STORY_API_TOKEN_PARAM=max_tokens|max_completion_tokens|none`（默认只发 `max_tokens`，不同时双发）。

## 示例产物（规则 + mock fixture 标注）
- `story_compose_phase3a_france.json` / `.md` / `_edl.json`
- `story_compose_phase3a_croatia.json` / `.md` / `_edl.json`
- `story_compose_mock_visual_fixture.json`（明确为 fixture，非识别准确率）

```bash
python -m story_video_agent --compose \
  --story-json "reports/story_t01/2022年11月23日 法国vs澳大利亚.json" \
  --causal-json "data/交付_out/2022年11月23日 法国vs澳大利亚_causal.json" \
  --out reports/story_compose_phase3a_france.json \
  --report-out reports/story_compose_phase3a_france.md
```

## Regression
58 OK（1 skipped billed smoke）。含结构、live 时序、证据引用、回放、none/candidate/story。
