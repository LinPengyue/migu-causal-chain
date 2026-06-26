# migu-causal-chain

咪咕视频因果链：**拆条因果链分类**（规则 + LLM Hybrid）+ **集锦因果链编排**（`causal_chain3`）。

本仓库包含两条主命令所需的代码、评测数据与示例时间线。

## 环境

```bash
cd causal-chain2
pip install -r requirements.txt
```

需 Python 3.9+、PyTorch；GPU 推理将 `--device cuda`（示例使用 `CUDA_VISIBLE_DEVICES=2`）。  
LLM 命令需本地 [Qwen2.5-VL](https://github.com/QwenLM/Qwen2.5-VL) 权重目录。

## 1）拆条因果链分类（`causal_chain2.test`）

**任务**：给定已切分的事件序列（`events_normalized`），判定其所属的 **18 类因果链模板**（如角球传中进球、VAR 改判无效、射门扑救等）。

**方法**：规则 Tool（CANONICAL 骨架 + 转移校验）排序 → 高置信 **Fast path**（不调 LLM）→ 歧义样本在 top-5 内 **Hybrid LLM 消歧**（0.35×LLM + 0.65×规则）。  
在 clean 评测集（654 条）上模板准确率约 **82%**。

```bash
CUDA_VISIBLE_DEVICES=2 python -m causal_chain2.test \
  --data eval/eval_a3_clean.jsonl \
  --eval-filter none \
  --model-path /data2/lpy1/Qwen2.5-VL \
  --device cuda
```

**输出示例**：

```
eval_filter=none  samples=654
backend=agent  mode=hybrid  samples=654  accuracy=0.8242  parse_fail=0  fast_path=527/654
```

| 参数 | 说明 |
|------|------|
| `--data` | A3 评测 jsonl（推荐 `eval_a3_clean.jsonl`，已去歧义样本） |
| `--eval-filter none` | 不再二次清洗（数据本身已是 clean 集） |
| `--model-path` | Qwen2.5-VL 权重目录 |
| `--backend` | 默认 `agent`（hybrid）；对照：`llm` / `gnn --ckpt ...` |

**可选**：

```bash
# 写每条样本的预测审计 JSON
python -m causal_chain2.test ... --agent-trace-dir out/agent_traces

# GNN 对照（仅 --ckpt，自动选 gnn 后端）
python -m causal_chain2.test \
  --data eval/eval_a3_clean.jsonl \
  --eval-filter none \
  --ckpt causal_chain2/_checkpoints/gnn.pt \
  --device cuda
```

## 2）集锦因果链（`causal_chain3.build_highlights`）

**任务**：输入 **整场拆条时间线**（事件 type + 时间戳），自动发现候选片段 → Hybrid 分类 → 抽取 **因果链结构**（events + edges + 叙事）→ 编排为集锦 reel。

**输出**：集锦方案 JSON（非 MP4 成片），每条 clip 含起止时间、链内事件、因果边、中文叙事；样例含 `ground_truth_chains` 可算命中率。

```bash
CUDA_VISIBLE_DEVICES=2 python -m causal_chain3.build_highlights \
  --timeline-json causal_chain/examples/full_match_timeline.json \
  --model-path /data2/lpy1/Qwen2.5-VL \
  --device cuda \
  --out out/reel_full_match.json \
  --viz-dir out/reel_viz
```

**输出**：

| 路径 | 内容 |
|------|------|
| `out/reel_full_match.json` | `reel.clips[]`：每条因果链 + `ordering` + `stats`（含 `ground_truth_accuracy`） |
| `out/reel_viz/` | 时间轴与各链事件条 PNG（需 `--viz-dir`） |

**示例时间线**：

| 文件 | 说明 |
|------|------|
| `causal_chain/examples/full_match_timeline.json` | 90 分钟完整比赛，43 事件，10 条标注因果链（检验用） |
| `causal_chain/examples/external_task2_timeline.json` | 短样例（2 条链） |

## 目录说明

| 路径 | 说明 |
|------|------|
| `causal_chain2/` | 拆条分类：schema / rules / agent hybrid / test / timeline_highlights |
| `causal_chain2/_checkpoints/gnn.pt` | LiteGCN 权重（GNN 对照） |
| `causal_chain3/` | 集锦因果链：discover → extract → refine → assemble → viz |
| `eval/eval_a3.jsonl` | 原始评测集（800 条） |
| `eval/eval_a3_clean.jsonl` | 清洗评测集（654 条，序列唯一对应模板） |
| `causal_chain/examples/` | 时间线 JSON 样例 |

## 相关仓库

GitHub：[LinPengyue/migu-causal-chain](https://github.com/LinPengyue/migu-causal-chain)
