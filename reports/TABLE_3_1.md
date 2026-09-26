# 8.31causal_chain 评测说明（离线 vs 流式拆条）

## 口径

| 列 | 含义 |
|----|------|
| 离线分类完整率 | gold 事件序列 → classify |
| 流式拆条成功率 | prefix replay + **candidate track 连续性关联** |
| B 上界 | oracle 输入边界 → strip → 配对（**不补事件 / 不时间平移**） |

Phase1：评测只造流；跨 prefix 记账用 track；不改 strip。rule-only，未接 Qwen。

## 冻结 baseline（P3）

| 项 | 值 |
|----|----|
| profile | `production` = `sliding_merge_mode=none` + `sliding_post_nms=off` |
| 流源 | `gold_events` + one-to-one matcher |
| offline / B / A | **90.62% / 81.46% / 76.66%** |
| precision / tracks | 74.28% / 451 |
| 回归入口 | `scripts/run_phase1_regression.sh` |
| 冻结文件 | `reports/baseline_phase1_frozen.json` |

暂不继续 P2 刷分；本轮后续转入集锦因果链（非 Top-N）。

## P0：gold↔track 一对一匹配（rule-only + gold_events）

| 指标 | 修正前（允许多 gold 命中同一 track） | 修正后（最大权一对一） |
|------|--------------------------------------|------------------------|
| 流式严格 | **74.37%** (325/437) | **64.76%** (283/437) |
| 流式精确 | **80.92%** (263/325)* | **87.08%** (283/325) |
| matched gold | 325 | **283** |
| unique matched tracks | 263 | **283** |
| candidate tracks | 325 | 325（未改） |
| B 上界 | 81.46% | **81.46%**（不变） |
| 离线严格 | 90.62% | **90.62%**（不变） |

\*修正前 `precision_hits` 按 unique track 计，但 recall 允许多 gold 共用 track，故 matched gold (325) ≠ unique tracks (263)。

不变量：`matched gold == unique matched tracks == 283`（`one_to_one_ok=true`）。

匹配：`scipy.optimize.linear_sum_assignment` + dummy 列；权重 = 最大化 strict 边数 ≫ 更早首次命中 ≫ 更高 IoU。strict 判定与 track 构造未改。

备份：`report_stream_strip_rule_gold_events_before_onetoone.json`  
最新：`report_stream_strip_rule_gold_events.json`

## rule-only 对照（timeline 诊断保留，主优化暂缓）

| 指标 | gold_events | timeline（识别流） |
|------|-------------|-------------------|
| 流式严格完整率 | 见 P0 最新报告 | **1.14%** (5/437) |
| 流式精确率 (track) | 见 P0 最新报告 | **1.42%** |
| candidate tracks | 见 P0 最新报告 | **351** |
| B 上界严格 | **81.46%** | **0.00%**（空切片 392/437；无 gold 回退） |
| 离线严格 | 90.62% | 90.62%（同口径，与流源无关） |

说明：timeline 旧口径曾在 oracle 空切片时回退 `gold.events`，B≈75.06%；已按「主评测不补事件」改为真实 timeline 切片，B=0%。该旧数仅作对照，见 `diag_timeline_vs_gold_events.json`。

## gold_events track 修复前后

| 指标 | 修改前（签名首次出现） | 修改后（track 连续） |
|------|------------------------|----------------------|
| candidate / emit 数 | 1474 | **325** |
| 流式严格 | 74.37% | **74.37%** |
| 流式精确 | 21.23% | **80.92%** |
| B / 离线 | 81.46% / 90.62% | 不变 |

## timeline ↔ gold 对齐（诊断，非主指标）

全量 437 条 gold：

| 类别 | 条数 |
|------|------|
| 附近完全无事件 (`no_events_near`) | 197 |
| 部分事件缺失 (`partial_missing`) | 122 |
| 附近有事件但类型对不上 (`no_matching_types_near`) | 110 |
| 仅时间偏移导致 oracle slice 空 (`time_shift_oracle_empty`) | 7 |
| timeline 事件基本完整 | 1 |

## 产物

- `reports/report_stream_strip_rule_gold_events.json`
- `reports/report_stream_strip_rule_timeline.json`
- `reports/diag_timeline_vs_gold_events.json`（对齐 + ge✓/tl✗ 归因）
- 基线：`reports/report_stream_strip_rule_before_track.json`
