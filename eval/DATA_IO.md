# 9.31 输入 / 输出约定

## 一、选哪个脚本

| 你有什么输入 | 脚本 | 产出 |
|--------------|------|------|
| **只有**上游事件 json（无 `*_causal.json`） | `eval/run_e2e_infer.py` | 每场拆条 + 集锦；**无**完整率 |
| 上游事件 + **成对** `*_causal.json` | `eval/run_e2e_eval.py` | 每场拆条 + 集锦 + **逻辑完整率** |

```bash
cd 9.31causal_chain
export PYTHONPATH="$PWD/algo:$PWD/eval"

# A. 仅推理
python eval/run_e2e_infer.py --src-dir data/交付_out --limit-matches 2

# B. 推理 + 评测（内部会先跑 build_datasets）
python eval/run_e2e_eval.py --src-dir data/交付_out --limit-matches 2
```

`scripts/build_datasets.py` 仍可单独跑；`run_e2e_eval` 默认会调用它。

---

## 二、目录放哪里

### 输入（两种脚本共用）

默认：`9.31causal_chain/data/交付_out/`

| 文件名 | 含义 |
|--------|------|
| `<比赛名>.json` | 上游事件识别输出（**无** causal） |
| `<比赛名>_causal.json` | 因果链标注（仅评测需要） |

配对规则：`foo.json` ↔ `foo_causal.json`（stem 完全一致）。

也可 `--src-dir /任意目录`，结构相同。

### 中间产物（仅评测脚本）

`run_e2e_eval` → `scripts/build_datasets.py` 写入：

```
datasets/
  index.json
  matches/<safe_id>/
    timeline.json          # 由 plain 转化
    strip_gold.json        # 由 causal 转化
    highlight_gold_no_t2.json
    highlight_gold_with_t2.json
    highlight_gold.json    # no_t2 别名
    meta.json
```

### 输出

| 脚本 | 目录 |
|------|------|
| `run_e2e_infer` | `reports/e2e_infer/<safe_id>/{timeline,strip,highlight}.json` + `_manifest.json` |
| `run_e2e_eval` | `reports/e2e_eval/<safe_id>/{strip,highlight}.json` + `_summary.json`（含完整率） |

---

## 三、上游事件 json（无 causal）必填结构

顶层：

```json
{
  "match_id": "字符串，比赛标识",
  "events": [ /* 见下 */ ]
}
```

可选：`schema_version` / `teams` / `video` / `annotation_scope` / `ignore_segments`（算法转化不依赖）。

**每个 event 最少需要：**

| 字段 | 说明 |
|------|------|
| `event_type` 或 `event_type_zh` 或 `comment_label` | 事件类型（英文/中文，会做归一化） |
| `media_time.event_time_sec` | 事件时刻（秒）；若无则用 `start_time_sec` |

推荐一并提供：

| 字段 | 说明 |
|------|------|
| `event_id` | 唯一 id |
| `media_time.start_time_sec` / `end_time_sec` | 窗起止（秒） |

示例：

```json
{
  "match_id": "示例比赛",
  "events": [
    {
      "event_id": "event_000001",
      "event_type": "Shot",
      "event_type_zh": "射门",
      "media_time": {
        "event_time_sec": 512.3,
        "start_time_sec": 508.0,
        "end_time_sec": 520.1
      }
    }
  ]
}
```

转化后写入 `timeline.json` 的内部事件形如：`{event_id, type, t_ms, t0_ms, t1_ms, order}`。

---

## 四、标注 `*_causal.json` 必填结构（仅评测）

顶层：

```json
{
  "match_id": "与 plain 一致为佳",
  "causal_chains": [ /* 见下 */ ]
}
```

**每条 causal_chain：**

| 字段 | 说明 |
|------|------|
| `chain_category` | 中文大类：`结果链` / `修正链` / `险情链` / `特殊链` |
| `events` | 链内事件列表（见下） |
| `is_replay` | `true` 的链会被丢掉 |

推荐：`annotation_id`、`causal_chain_subtype`、`segment_time_sketch` / `segment_time_video`。

**链内每个 event：**

| 字段 | 说明 |
|------|------|
| `type` 或 `type_en` | 类型（中/英） |
| `t_ms` | 时刻（**毫秒**） |
| `order` | 链内顺序 |

示例：

```json
{
  "match_id": "示例比赛",
  "causal_chains": [
    {
      "annotation_id": "ann_001",
      "chain_category": "结果链",
      "causal_chain_subtype": "射门进球链",
      "is_replay": false,
      "events": [
        {"order": 0, "type": "传球", "type_en": "Pass", "t_ms": 512000},
        {"order": 1, "type": "射门", "type_en": "Shot", "t_ms": 515000},
        {"order": 2, "type": "进球", "type_en": "Goal", "t_ms": 516200}
      ]
    }
  ]
}
```

---

## 五、完整率字段（仅 `run_e2e_eval` → `_summary.json`）

`logic_complete_rates`：

| 键 | 含义 |
|----|------|
| `strip_module` | 离线拆条模块口径（约 82%） |
| `strip_online` | 在线拆条口径（约 71%） |
| `strip_timeline` | 整场 timeline 预测再对 gold |
| `highlight_offline` | 离线集锦口径（约 50%+） |

每项含 `rate` / `matched` / `gold`。

---

## 六、注意

1. **无 causal 不能报完整率**——没有 gold 分母。  
2. 评测要求 plain 与 causal **成对**；只有 plain 的场次不会进 `build_datasets`。  
3. 上游换新目录时，把同名 plain（及可选 causal）放进 `--src-dir` 即可。
