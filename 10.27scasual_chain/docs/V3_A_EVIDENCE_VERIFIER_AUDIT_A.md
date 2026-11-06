# V3-A 零付费证据一致性与 Verifier 解析失败审计

**分支**: `story-va-v3a-evidence-verifier-audit-A`  
**约束**: HTTP=0；不重跑实验；不改冻结 EDL；不调用付费 API。  
**对比实验**:

| 标签 | 路径 |
|------|------|
| OLD | `/data2/lpy1/_story_va_outputs/v3/plan2/A_one_round_opening_20261106_133900` |
| NEW | `/data2/lpy1/_story_va_outputs/v3/plan2/A_post_vlm_real_20261106_151951` |

---

## 任务一：Qwen 两次观察为何不同

### 结论（证据充分部分）

**视觉输入相同；模型解释随机发散；字段与叙述存在自相矛盾。未发现解析映射改写布尔字段的证据。**

### 1.1 帧 SHA256（字节级相同）

实际 PTS（manifest `actual_media_sec`）两次均为：`1334.64 / 1336.36 / 1337.76 / 1339.16`。

| 帧 | SHA256 | 对比 |
|----|--------|------|
| `f_0000_1334623.jpg` | `31e72d826beb83bd47dc6cd8aee79da4119382549f1987d6d581861aa61000b5` | IDENTICAL |
| `f_0001_1336323.jpg` | `2dfeabffecd935cc85a6dd2ec019f54196fdce6124d61b55dd9118906bb7e763` | IDENTICAL |
| `f_0002_1337723.jpg` | `dc08e549972e7ceb53fb41da03381b1236fa31476cafc4ba8719980ddec5dc45` | IDENTICAL |
| `f_0003_1339123.jpg` | `a54799957591258c911d761e9fb5b087868815b0386de922bed43f45d6fab349` | IDENTICAL |

→ **排除「抽帧内容不同」作为根因。**

### 1.2 请求 / 模型 / 采样配置

| 项 | OLD | NEW |
|----|-----|-----|
| model | `Qwen3.6-Plus` | 同 |
| `prompt_tokens` | **8616** | **8616**（相同） |
| `completion_tokens` | 449 | 480 |
| `request_token_param` | `max_tokens` | 同 |
| `request_token_limit` | 2048 | 同 |
| `request_thinking_sent` | true | 同 |
| `finish_reason` | `stop` | `stop` |
| window | `[1321.123, 1351.123]` | 同 |
| `sample_times` | `1334.623…1339.123` | 同 |
| `question`（进 prompt） | `""` | `""` |
| `anchor_id` | `edl:seg_opponent_opening_goal_action` | 同 |
| `request_id` / gap_id | `tool_001_opponent_goal_action_inspect` | `tool_001_opponent_opening_goal_action` |

完整原始 HTTP body 未落盘；但 **相同 prompt_tokens + 相同图像 SHA + 相同 window/anchor/空 question** 强烈支持：文本提示与图像输入在 token 层面等价。`request_id` 字符串差异不进入 VLM user prompt 主体（仅影响帧 gap 命名；帧 id 仍按 PTS 生成且一致）。

→ **排除「不同模型 / 不同采样上限 / 不同帧内容」；采样为非确定性生成（temperature 未强制 0 的默认路径）。**

### 1.3 原始响应与结构化字段

| 字段 | OLD | NEW |
|------|-----|-----|
| `observed_shot` | true | true |
| `observed_net` | true | true |
| `supports_bound_segment` | **true** | **false** |
| `candidate_goal_action_span` | window 整段 | **null** |
| `scoreboard_only` | false | false |
| `live_or_replay` | live | live |
| 叙述 | 球进网；0-0 为进球前；庆祝 | **未进球 / 解围或扑救；0-0 表示未进球** |
| `next_search_request` | null | 请求窗外搜索（后被 schedule 拒绝） |

结构化字段直接来自模型 JSON（`_parse_model_json` 成功路径）；**没有后处理把 shot/net 改写为 true 的证据。**

### 1.4 `observed_shot` / `observed_net` / `supports_bound_segment` 与文字

- **OLD**：叙述「进球」与 `shot=true, net=true, supports=true` **一致**；把记分牌 0-0 解释为**进球前比分**。
- **NEW**：叙述「未进球 + 0-0」与 `supports_bound_segment=false` **一致**；但与 `observed_shot=true` **且** `observed_net=true` **矛盾**。

因此 NEW 同时存在：

1. **模型解释差异**（同像素两次不同故事）；  
2. **字段定义歧义 / 模型自洽失败**（`observed_net` 似被当成「球在球门附近」而非「球入网」）；  
3. **0-0 记分牌被 NEW 误用作「未发生进球」的充分证据**——这是解释策略错误，不是帧上已显示改分。稀疏 4 帧本就可能拍不到比分变化瞬间。

### 1.5 根因分层（不强行单因）

| 层级 | 判定 |
|------|------|
| 视觉内容差异 | **否**（SHA 相同） |
| 模型解释差异 | **是**（同输入、不同叙述与 supports） |
| 字段定义歧义 | **是**（NEW：net=true 却否认进球） |
| 解析映射错误 | **无证据**（字段按模型原文入库） |

**未解决问题**：是否应在 schema/提示中强制 `observed_net ⇒ 球明显入网` 与 prose 一致性校验；是否提高采样密度或覆盖比分变化前后。本次审计**不**据此改冻结 EDL 或重跑付费 VLM。

---

## 任务二：Verifier 为什么解析失败

### 结论

**HTTP 成功；可见输出在 `max_tokens=2048` 天花板被截断（`finish_reason=length`，`completion_tokens=2048`）；失败发生在 `_parse_model_json` → `_extract_json_obj`，未到达 `validate_verifier_output`。**  
旧失败码 `STRUCTURED_PARSE_FAIL` 掩盖了预算截断；审计前 `output_budget_exceeded` 因使用 `ct > limit` 在 `ct==limit` 时为 false。

### 2.1 保存的真实响应与异常

NEW `dual_verifier.json` / `api`:

- `failure_code`: `STRUCTURED_PARSE_FAIL`
- `error`: `STRUCTURED_PARSE_FAIL:EvidenceNormalizationError:invalid JSON object`
- `http_ok=true`, `generation_ok=true`, `structured_ok=false`
- `usage.completion_tokens=2048`, `reasoning_tokens=0`
- `raw_excerpt` 仅保存前 **2000** 字符（完整可见输出约 **7984** 字符，见 `api_usage.records`）

`self_revise_summary.json` → verifier record:

| 字段 | 值 |
|------|----|
| `finish_reason` | **`length`** |
| `completion_tokens` | **2048** |
| `request_token_limit` | **2048** |
| `visible_output_chars` | 7984 |
| `output_budget_exceeded`（当时） | **false**（缺陷：`ct > limit` 未覆盖相等） |

OLD Verifier 对照：`completion_tokens=412`, `finish_reason=stop`, JSON 完整可解析，`structured_ok=true`。

### 2.2 离线复现（真实失败，非模拟成功）

对 NEW 保存的 `raw_excerpt`：

```
json.loads → JSONDecodeError: Unterminated string …
_extract_json_obj → EvidenceNormalizationError: invalid JSON object
_parse_model_json → 同上（未进入 validate_verifier_output）
生产错误串完全一致：
STRUCTURED_PARSE_FAIL:EvidenceNormalizationError:invalid JSON object
```

说明：完整 7984 字符原文未落盘；excerpt 已足够证明**不完整 JSON**；结合 `finish_reason=length` + `ct==2048`，截断根因证据充分。

### 2.3 失败步骤定位

1. `_parse_model_json` / `_extract_json_obj` ← **失败点**  
2. `validate_verifier_output` ← **未执行**

### 2.4 2048 限制是否导致截断

**是。** `finish_reason=length` 且 `completion_tokens == request_token_limit == 2048`。  
NEW Verifier prompt 更大（3458 vs OLD 2685），输出更冗长（issues 列表），在相同 2048 天花板下更容易触顶。

---

## 任务三：最小修复（仅针对已证实问题）

已在本分支落地（零付费单测：`tests/test_v3a_evidence_verifier_audit_A.py`）：

1. **`OUTPUT_BUDGET_TRUNCATION`**：`call_llm_verifier` 在 parse 失败且 `finish_reason=length` 或 `completion_tokens >= limit` 时使用该 `failure_code`；记录 `parse_stage` / `finish_reason`。  
2. **天花板相等即超预算**：`api_provider` 将 `ct > limit` 改为 **`ct >= limit`**（审计标志；硬熔断仍受既有 `truncated_empty` / env 约束）。  
3. **`NO_CANDIDATE_CHANGE` 跳过付费 Verifier**：当 Revision Planner 决策为 `KEEP` / `KEEP_WITH_NEW_EVIDENCE` / `UNRESOLVED`，且 pre/post EDL SHA 相同、`evidence_bound_count==0` 时，只跑 Rule track，语义标记 `SKIPPED_NO_CANDIDATE_CHANGE`，`est_cost_usd=0`。  
   - 直接对应 NEW 实况：`decision=UNRESOLVED`，pre/post SHA 均为 `7e0afefe…`，却仍付费调用了被截断的 Verifier。

**未改**：冻结 EDL；VLM 提示词；付费重试；盲目抬高 max_tokens（未证实单独足够且会增加成本）。

---

## 未解决问题

1. Qwen 在相同像素上的随机性与 `observed_net` 语义歧义——需 schema/一致性门，而非本次范围。  
2. Verifier 完整 raw（>2000 字符）未持久化——审计依赖 excerpt + usage；建议后续失败路径落盘完整 content（仍零付费改代码即可，本 PR 未扩 scope）。  
3. 若未来 KEEP 但带 evidence-bound 元数据变更，当前 skip 条件要求 `evidence_bound_count==0`，行为保守。

---

## 回归

```text
PYTHONPATH=algo python3 -m unittest tests.test_v3a_evidence_verifier_audit_A -v
# 11 tests, HTTP=0
```
