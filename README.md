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
| `causal_chain4/` | 分类 classify + 拆条 strip（标注 JSON 映射可配） |
| `eval/eval_a3.jsonl` | 原始评测集（800 条） |
| `eval/eval_a3_clean.jsonl` | 清洗评测集（654 条，序列唯一对应模板） |
| `causal_chain/examples/` | 时间线 JSON 样例 |

## 3）causal_chain4：分类 + 拆条

与 `causal_chain2` **并列**；核心对齐 chain2 两条命令，并支持 **causal JSON 映射**（`profile` 配置）。

| chain4 | 对齐 chain2 | 输入 |
|--------|-------------|------|
| **`classify`** | `causal_chain2.test` | A3 jsonl 或 `*_causal(2).json` |
| **`strip`** | `causal_chain2.timeline_highlights` | 整场 `timeline.json` |

评测只看 **template 准确率**；转移合法率仅在 `eval --show-transition-debug` 时出现。

### 3.1 因果链分类

默认后端 **`chain4_agent`**：使用 `causal_chain4/schema/skeletons.py` 业务骨架（长链、其他三子类），**不修改** `causal_chain2` 规则。

```bash
ROOT=/path/to/causal-chain2
PY="$ROOT/causal_env/bin/python"
MODEL="$ROOT/Qwen2.5-VL"
cd "$ROOT" && export PYTHONPATH=.

# 业务骨架分类（causal JSON；无 GPU 也可纯规则）
"$PY" -m causal_chain4.classify \
  --data causal_chain/examples/10月10日_2025世预赛欧洲区_哈萨克斯坦VS列支敦士登_英语_causal\(2\).json \
  --profile oct10_causal2 \
  --backend chain4_agent \
  --device cpu \
  --out-predictions eval/oct10_kz_chain4_skel_preds.jsonl

# 带 Qwen hybrid（歧义时消歧）
CUDA_VISIBLE_DEVICES=0 "$PY" -m causal_chain4.classify \
  --data causal_chain/examples/..._causal\(2\).json \
  --profile oct10_causal2 \
  --model-path "$MODEL" \
  --device cuda

# 对照：复用 chain2 agent（旧 18 类短骨架）
CUDA_VISIBLE_DEVICES=0 "$PY" -m causal_chain4.classify \
  --data eval/eval_a3_clean.jsonl \
  --backend agent --eval-filter clean \
  --profile strict_chain2 \
  --model-path "$MODEL" --device cuda
```

指标：`accuracy` 精确匹配；`soft_accuracy` 将「其他」与个人突破/团队配合/角球配合视为一致。

骨架与长度见 `causal_chain4/schema/skeletons.py`、`SKELETONS.md`。

### 3.2 拆条

```bash
CUDA_VISIBLE_DEVICES=0 "$PY" -m causal_chain4.strip \
  --timeline-json causal_chain/examples/external_task2_timeline.json \
  --model-path "$MODEL" \
  --device cuda \
  --profile production \
  --out out/chain4_highlights.json \
  --min-margin 0.08 \
  --max-events 12 \
  --viz-dir out/chain4_viz
```

可选：`pipeline` / `extract` / `eval` 为实验与标注对比子命令。

## 相关仓库

GitHub：[LinPengyue/migu-causal-chain](https://github.com/LinPengyue/migu-causal-chain)
