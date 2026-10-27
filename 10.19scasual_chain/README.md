# 8.31causal_chain

## 1. 项目说明

`8.31causal_chain` 用于足球赛事因果链分析，包含：

**拆条因果链**（结果链 / 修正链 / 险情链 / 特殊链）
- 离线拆条
- 在线流式拆条
- Qwen 可选辅助分类

**集锦因果链**（`follow` / `same_sequence` / `correction_of`）

本版本不包含五佳球 / 十佳球 Top-N。

## 2. 总体流程

```
Event/Timeline
  ├─ Offline → causal_chain6 strip
  └─ Online  → OnlineStripEngine
                    ↓
             Strip Causal Chains
                    ↓
             causal_chain8
                    ↓
             Highlight Chain
```

## 3. 目录说明

| 目录 | 说明 |
|------|------|
| `algo/causal_chain6` | 拆条因果链 |
| `algo/causal_chain8` | 集锦因果链 |
| `eval` | 评测脚本 |
| `reports` | 评测结果 |
| `datasets` | 测试数据 |

## 4. 环境

```bash
cd 8.31causal_chain
pip install -r requirements.txt
export PYTHONPATH=$PWD/algo:$PWD/eval
```

**Qwen（可选）**：建议使用 conda 环境 `mllms_know`，避免 base 环境中 `transformers` 路径污染。

```bash
# 示例（在 8.31causal_chain 根目录）
conda run -n mllms_know python eval/run_causal_chain_selftest.py
# 或先 conda activate mllms_know 再运行 python ...
```

模型权重通过 `--model-path` 传入（相对或本机路径均可），例如：

```bash
python eval/run_eval.py --use-llm --model-path ./models/Qwen2.5-VL --device cuda
```

默认评测为 **rule-only**，不加载 Qwen。文档与报告均使用相对包根路径，便于打包到服务器。

## 5. 四种正式评测

```bash
# 1 离线拆条因果链
python eval/eval_offline_strip.py --event-source gold_events

# 2 离线集锦因果链
python eval/eval_offline_highlight.py

# 3 在线拆条因果链
python eval/eval_online_strip.py --stream-source gold_events

# 4 在线集锦因果链
python eval/eval_online_highlight.py --stream-source gold_events
```

统一入口（顺序跑上述 4 项）：

```bash
python eval/run_causal_chain_selftest.py
```

说明：
- 默认跑全量 **63** 场
- 运行时 `tqdm` 实时显示累计成功率
- 最终结果同时 print，并写入 `reports/*.json`
- `--limit-matches` 仅用于调试（如 `--limit-matches 2`）

## 6. 评测口径

拆条 / 集锦 **逻辑完整率** 均采用一对一 strict：

1. 时间区间有交叉
2. `category` 一致
3. `first_event` 一致
4. `last_event` 一致
5. 一条 gold 最多匹配一条 pred

区分：
- **offline**：完整离线输入
- **online**：严格按事件到达顺序，不允许未来信息

Highlight 补充：
- `annotation-only`：人工标注子集
- `timeline_heuristic`：启发式标签
- **P5 structural pass** 与 **logic complete rate** 是两个不同指标（结构回归 ≠ 逻辑完整）

## 7. 当前 rule-only 全量结果

| Task | Gold | Matched | Logic Rate | Precision |
|------|------|---------|------------|-----------|
| Offline Strip | 437 | 359 | 82.15% | 93.01% |
| Online Strip | 437 | 313 | 71.62% | 72.79% |
| Offline Highlight (all) | 172 | 105 | 61.05% | 61.05% |
| Offline Highlight (annotation) | 114 | 65 | 57.02% | — |
| Online Highlight (all) | 164 | 0 | 0% | 0% |

**Online Strip 时延**：Latency P50=60.0s，P90=167.4s，>45s=68.05%

**P5 structural**（非逻辑完整率）：
- offline：63/63 pass
- online：60/60 pass
- nodes 无丢失 / 无重复、无环、ordering / correction 正常

汇总文件：`reports/causal_chain_selftest_summary.json`

## 8. Qwen

开启方式（在对应评测 / adapter 入口上）：

```bash
... --use-llm
```

当前全量 online strip 对比：

| 模式 | Strict |
|------|--------|
| rule-only | 71.62% |
| Qwen | 71.85% |

当前 Qwen 无明显指标提升，**默认仍使用 rule-only**。

## 9. 输出结果

评测汇总：`reports/causal_chain_selftest_summary.json`（看 `summary_table`）。  
分项报告：`reports/eval_offline_strip.json` 等。

### 9.1 评测 JSON 字段

| 字段 | 含义 |
|------|------|
| `gold` / `total_gold` | gold 条数（分母） |
| `matched` / `strict_matched` | 一对一 strict 命中条数 |
| `logic_rate` / `logic_complete_rate` | 逻辑完整率 = matched / gold × 100 |
| `precision` | 命中 / 预测条数（拆条为 pred/track 分母；集锦为 clip 分母） |
| `n_unscorable` | 无法评分条数（如 timeline 窗空）；不计入 gold |
| `latency_p50` / `latency_p90` | 首次 strict 命中相对 gold 就绪时刻的时延（ms） |
| `over_45s_rate` | 时延 > 45s 的比例 |
| `annotation_only` | 仅 `label_source=annotation` 的 gold 子集 |
| `timeline_heuristic_only` | 仅启发式标签子集 |
| `label_source_counts` | 上述两类 gold 条数（不改 gold） |

**P5 structural**（不是逻辑完整率）：

| 字段 | 含义 |
|------|------|
| `pass_rate` / `n_pass` / `n_fail` | 场次结构通过率 |
| `node_loss` | 图节点数 ≠ strip 条数的场次数 |
| `duplicate` | 节点 id 重复 |
| `cycle` | 有环 |
| `ordering` | 排序不稳定 |
| `correction` | `correction_of` 时序方向错误 |

`logic_complete_rate=null` 表示本批没有有效 highlight gold，此时只报 structural。

### 9.2 算法输出字段（链本身）

**Strip chain**：`chain_category` / `first_event` / `last_event` / `t0_ms` / `t1_ms` / `template_id` / `events`

**Highlight chain**（P5 图）：`nodes` / `edges`（`rel` ∈ `follow` \| `same_sequence` \| `correction_of`）/ `highlight_chain.ordering`

集锦**逻辑完整率**评的是 highlight **clips**（`select_moments` → classify/refine），不是 P5 全量 graph nodes。

## 10. 已知限制

- online 时延受 `post_ms` / `window_ms` 影响
- online highlight 当前逻辑完整率仍需优化
- detector timeline 存在漏检 / 错型 / 时钟对齐问题，因此 `gold_events` 作为当前 causal-chain 单模块自测源
- 本轮不支持 Top5 / Top10
