# V1 Agent 接入审计（相对 V3 闭环 · 只读）

**范围：** 冻结 `2d1ec9c` 规则基线闭环 vs V1 `runner.solve` / ToolBox / VisionProvider / Verifier / Composer  
**本轮：** 不修改实现；不启用付费 API / 新 Agent 模式。

## 当前 V3 闭环实际调用了什么

```
atomic_event_enrich
  → v2_strip_reinfer.run_strip_predict (AlgoStripAdapter, use_llm=False)
  → v1_causal_adapter.strip_chains_to_v1_causal
  → phase5_pipeline.run_phase5
       → story_chain.end_to_end.run_paths (T01)
       → narrative_composer.compose_story_plan(..., use_llm=False)   # Composer 规则路径
       → phase5_delivery.select_delivery_rows / render_dual_delivery  # ffmpeg
```

**未调用：** `story_video_agent.runner.solve`、`Agent`、`ToolBox`、`VisionProvider`（本基线）、`story_verifier.verify_story` 作为门禁签发。

## 组件对照

| V1 组件 | 职责 | V3 闭环接入状态 | 缺失连接 / 数据接口 |
|---------|------|-----------------|---------------------|
| `runner.solve` | dry_run / media_only / perception 证据环；组装 Agent+ToolBox+Memory+trace | **未接入** closed_loop / phase5 | 无「story item → solve → evidence_tasks」管道；phase5 不消费 solve trace |
| `Agent` + LLM/规则 planner | 逐步选 tool / finish | **未接入** | 缺 V3 侧 `build_agent_item(story)` 与 gap 列表对接闭环产物 |
| `ToolBox` | probe / gaps / sample / inspect / scoreboard / reaction | **未接入** 基线渲染 | 缺把 EDL `goal_action` 窗注册为 gap 的接口；缺 FrameStore 输出目录约定接入 `04_phase5` |
| `VisionProvider` | 帧级 VLM 描述（经 ApiProvider） | 基线 **禁用**；仅存在于 `v3/remote_vlm_verify.py` 等旁路 | 缺「闭环正式阶段」的 provider 注入点与 `force_mock/require_real` 门闩；本轮禁止付费调用 |
| `story_verifier` (Verifier) | 比分/归属/时序/回放/视觉一致性 | Composer 内部可能引用检查，但 **不作为** phase5 `render_ready` 签发器 | 缺 verifier 报告 → phase5_manifest.gates 的硬接口；无 `pipeline_verified=true` 回写 EDL |
| `compose_story_plan` (Composer) | T01→可剪辑 plan/EDL | **已接入**（`use_llm=False`） | 旁白 LLM 路径未开；与 Agent 感知证据的 `visual_evidence` 字段 **未打通** |
| ApiProvider | 远程 LLM/VLM 配置 | 闭环基线不实例化 | 缺统一「V3 run config：paid_api=0」强制开关与审计计数器接到 runner |

## 数据接口缺口（若未来要接回 V1 Agent）

1. **Input contract：** `solve(story, video_path=..., perception=True)` 需要的 `story` 是否等于 `t01_story.json` + `story_plan.json` 合并，尚未定义。  
2. **Gap contract：** ToolBox `list_story_gaps` 依赖 story 内 gap schema；phase5 EDL roles（`equalizer_goal_action` 等）无自动映射为 gap_id。  
3. **Evidence sink：** `evidence_tasks[].visual_evidence` / FrameStore manifest 无写回 `candidate_edl.json` / `time_provenance.pipeline_verified`。  
4. **Verifier sink：** `verify_story` 结果无驱动 `render_ready`（phase5 恒 false）。  
5. **Isolation：** Agent 感知缓存目录不得与场次 gold/EDL 混用；需独立 `05_agent_perception/`。

## 结论

V3 规则基线 = **8.31 规则拆条 + Composer 规则编排 + ffmpeg 交付**。  
V1 Agent 感知闭环（solve/ToolBox/Vision/Verifier）在架构上相邻，但 **调用链与数据接口均未接到** 当前 `closed_loop_cli`；本审计不实施改动。
