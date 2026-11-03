# V1 Video Agent / 8.31 执行轨迹（A/B 冻结）

**paid_api_calls:** 0  
**human_causal_structure_into_831_or_v1:** false（仅原子 type/t_ms/is_replay 补全）  
**fully_automatic_detection_claimed:** false

## 阶段与调用性质

| 阶段 | 实现 | 调用性质 | 缓存 |
|------|------|----------|------|
| 原子事件补全 | `atomic_event_enrich.enrich_files` | **规则**：从 `*_causal.json` 抽原子字段写入交付 events 副本；`enrichment.provenance=causal_atom_fill` | 无模型缓存；产物 `01_enrich/` |
| 8.31 拆条 | `v2_strip_reinfer.run_strip_predict` → `AlgoStripAdapter(use_llm=False, use_sliding_recall=True)` | **本地规则/算法推理**，非付费 API，非 LLM | 每次对 enriched timeline 重跑；产物 `02_strip831/strip_A_original.json` |
| V1 适配 | `v1_causal_adapter.strip_chains_to_v1_causal` | **规则映射**（含 Goal→进球）；过滤 REPLAY Goal 链/原子后供 phase5 | `03_v1_adapt/` |
| T01 识别 | `phase5_pipeline.run_paths` → T01 | **规则** | `04_phase5_*/t01_story.json` |
| 故事编排 | `compose_story_plan(..., use_llm=False)` | **规则**（无 LLM 旁白） | `story_plan.json` |
| 交付 EDL/渲染 | `select_delivery_rows` + `render_dual_delivery` + ffmpeg | **规则 + ffmpeg** | `candidate_edl.json` / `story_clean.mp4` |

## 人工补全标记

enriched 事件带：
```json
"enrichment": {
  "provenance": "causal_atom_fill",
  "source_event_ids": ["..."],
  "copied_fields": ["type", "t_ms", "is_replay"],
  "forbidden_copied": ["chain_category", "causal_chain_subtype", "segment_time_video", "edges", "story"]
}
```
禁止将本结果宣称为「全自动检测进球」。

## 配置要点

- `use_llm=False`（8.31 与 V1 composer）
- `glitch_profile=None`
- Pass3：buildup 与 goal_action 重叠≥50% 丢弃
- 无归因角球/定位球蓄力丢弃
- clean 叠字 `overlay_anchor=bottom_left`；剥离不可靠分钟标
