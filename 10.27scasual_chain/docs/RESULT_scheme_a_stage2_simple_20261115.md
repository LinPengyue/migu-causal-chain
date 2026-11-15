# Scheme A 简化第二阶段 — 生成+评分（2026-11-15）

HEAD（运行时）: `69cd162`  
产物目录: `/tmp/lpy1_scheme_a_stage2_simple_20261115/` 与 `docs/artifacts_scheme_a_stage2_simple_20261115/`  
模型: `DeepSeek-V4.1-Flash`，thinking disabled。无 VLM / 未改 EDL / 未进 Planner。

## 费用与 HTTP

| 步骤 | HTTP | prompt | completion | est_usd |
|------|-----:|-------:|-----------:|--------:|
| 生成 max5 | 1 | 64258 | 593 | 0.009994 |
| 评分 | 1 | ~13895（实测；audit 字段 null） | — | 0.002576 |
| **合计** | **2** | | | **≈0.01257** |

生成 `finish_reason=stop`；评分 `finish_reason=stop`，`status=REAL_MODEL_PRIOR_NOT_VIDEO_VERIFIED`。

## 生成结果（请求最多 5，实际接受 3，未人工凑数）

| ID | mechanism | 摘要 | 事件 |
|----|-----------|------|------|
| H1 | var_penalty_denial_precedes_equalizer | VAR取消点球后持续施压并扳平 | 617,622(REPLAY),635,472 |
| H2 | substitution_shift_enables_late_pressure | 换人后进攻增强并扳平 | 563,564,598,472 |
| H3 | repeated_dribble_breaks_build_momentum | 多次过人累积势头并扳平 | 575,580,590,472 |

历史 Run02 H1/H2 仅作参照，见 `HISTORICAL_*`。

## 评分排名（观察先验，非因果证明）

| 排名 | ID | priority | 五维 (A/I/J/M/E) | 要点 |
|-----:|----|---------:|------------------|------|
| 1 | H1 | 0.50 | 2/2/2/2/2 | 新增 VAR 取消点球情节；622 为 replay；因果未证 |
| 2 | H2 | 0.25 | 1/1/1/1/1 | 换人/长传相对 EDL 新，但战术转变无事件支撑；472 时序在换人前 |
| 3 | H3 | 0.25 | 1/1/1/1/1 | 三次过人相对 EDL 新，与扳平关联未证 |

`selected_for_video_observation`: H1,H2,H3；`planner_eligible=false`；`first_live_certified=false`。

详细评分理由见 `03_score_real/scheme_a_story_ranking.json` 与 `llm_raw_response.txt`。
