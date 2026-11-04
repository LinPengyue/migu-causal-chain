# V3-A Verifier loop retain vs release gate

**分支：** `story-va-v3-a`  
**本轮付费 API：** 否 · **冻结 V3-R 未改**

## 原则

Verifier **服务 Agent 自修订**，不是每轮最终交付审核。

| 门禁 | 作用 |
|------|------|
| `decide_accept(mode=loop)` | 是否保留候选进入下一轮 |
| `decide_release()` | 是否具备正式交付资格（默认仍 `NOT_AUTHORIZED`） |

实验综合阈值：`DEFAULT_QUALITY_THRESHOLD = 75`（可配置，**未校准**）。

## 决策示例（合成回归）

### 1. FR：P0 未清零，局部叙事改善 → 循环保留

- 基线缺 opening（feedback P0）+ 无关 filler  
- 候选：drop filler，opening 仍缺  
- **path=`quality_improvement` / `partial_improvement`，`accept=true`，`release_eligible=false`**

### 2. A/B/C：结构完整，删无关镜头 → 保留

- **path=`quality_improvement`，`accept=true`**

### 3. API Verifier 502 + 规则侧连贯性上升 → 循环保留

- reasons 含 `api_verifier_degraded_rule_track_active`  
- **`accept=true`，语义 NOT_EVALUATED，不可 release**

### 4. UNKNOWN ≠ 0

- `composite_quality_score` 排除 NOT_EVALUATED 维；有规则代理则用规则分

### 5. 确认回放 / hard veto → 拒绝

- `replay_as_primary` 或 `hard_vetoes` → **`accept=false`**

### 6. 未核验进球绑定

- 循环：`path=loop_pending_verification`，可保留提案  
- 交付：`decide_release` → **`release_eligible=false`**

## 回归

```text
66 / 66 OK  (test_v3a_*.py，含 test_v3a_verifier_loop_relax)
```
