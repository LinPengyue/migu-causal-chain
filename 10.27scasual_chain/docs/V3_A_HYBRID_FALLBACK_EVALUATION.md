# V3-A Hybrid API Fallback Evaluation

**分支：** `story-va-v3-a`  
**合约：** `docs/V3_A_HYBRID_API_FALLBACK_CONTRACT.md` + `docs/V3_A_AGREED_DESIGN_CONTRACT.md`  
**本轮付费 API：** **否**  
**V3-R / 冻结 EDL·MP4 重渲：** **否**

---

## 1. 能力实现对照

| 项 | 状态 |
|----|------|
| Rule Verifier 始终运行 | **已实现**（`hybrid_fallback.run_rule_verifier` / Stage-1 `evaluate`） |
| API Verifier 语义评价 | **已实现**；失败后语义维 = `NOT_EVALUATED`（非 0/100） |
| 502/超时有限重试后降级 | **已实现**（`call_llm_verifier` + `run_dual_verifier`） |
| 不把规则通过冒充语义通过 | **已实现**（`semantic_pretend_pass=false`；goal bind 需 semantic PASSED） |
| Planner API 失败 → 规则缺口任务 | **已实现**（`build_rule_planner_fallback`，无凭空语义修订） |
| VLM API 失败 → FFmpeg/PTS 继续 | **已实现**（`run_ffmpeg_observe_without_vlm`；语义 UNKNOWN） |
| 编排状态字段 | **已实现**（见 summary / `build_orchestration_status`） |
| 保留最佳已接受 EDL | **已实现**（拒绝候选时回滚到 `best`） |

模块：`hybrid_fallback.py`；编排：`self_revise_agent.run_self_revise`（`--allow-degraded-offline`）。

---

## 2. 测试结果

```bash
PYTHONPATH=10.27scasual_chain/algo \
python -m unittest discover -s 10.27scasual_chain/tests -p 'test_v3a_*.py' -q
```

| 结果 | 值 |
|------|----|
| 总计 | **58 / 58 OK** |
| 新增 `test_v3a_hybrid_fallback` | 8 OK（Planner/VLM/Verifier 故障注入、三 API 同挂、goal bind 拒绝、hard veto） |
| Stage-3 `test_cannot_use_changed_phase5_files` | **已修复**（fixture 对 `source_sha256` 做 dict 拷贝，消除别名） |
| 仍存问题 | CLI 单测里偶发 “proposal output already exists” 打印（既有行为，用例仍标 ok） |

故障注入覆盖：

1. Planner 故障 → `workflow_completed` + 基线 EDL + 规则报告  
2. VLM 故障注入 → ffmpeg 路径 / semantic UNKNOWN  
3. Verifier 故障 → Rule 仍跑；语义 NOT_EVALUATED；不接受不可靠修订  
4. 三 API 同挂 → 降级输出；冻结 phase5 字节不变  
5. 编排状态区分 degraded vs multimodal success  
6. hard_veto / 无语义 goal bind → 拒绝  

---

## 3. 真实 API / 真实 EDL / 成片

| 问题 | 答案 |
|------|------|
| 本轮真实 API 调用？ | **否** |
| 冻结 EDL 被改？ | **否** |
| 成片质量因多模态修订提升？ | **否**（未跑真实联调） |
| 降级执行成功？ | **是**（合成故障注入下 `workflow_completed` + `degraded_execution_success`） |
| 多模态自修订成功？ | **否**（`multimodal_self_revision_success=false` 于故障路径） |

---

## 4. 术语区分（必须）

- **降级执行成功** = 规则链路与报告完成，基线/最佳 EDL 保留，`render_ready=false`。  
- **多模态自修订成功** = 真实模型参与 + 证据绑定修订被接受 + 可核验改善（`agent_contributed_improvement=true`）。

二者不可互换。

---

## 5. 下一步

在显式额度授权下做法国场小预算真实联调，验证 API 恢复后可继续修订且不丢失 best EDL；仍禁止把降级成功写成成片改善。
