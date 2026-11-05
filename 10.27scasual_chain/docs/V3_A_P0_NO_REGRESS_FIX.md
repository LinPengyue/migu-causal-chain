# V3-A P0：A 场质量退化修复（独立分支，无付费 API）

**冻结对照（未改）：** 实验代码 `2fc6b16` · 报告 HEAD `e92070f` · 分支 `story-va-v3-a`  
**本修复分支：** `story-va-v3-a-p0-no-regress`  
**付费 API：** 无  
**A 场进球时间硬编码：** 无

---

## 1. 基线是否拿错？——**是**

| 产物 | `phase5_dir` / EDL | opening 窗 | EDL SHA256（前 16） | MP4 时长 |
|------|-------------------|------------|---------------------|----------|
| `04_phase5`（V3-A 评测实际输入） | raw | 1386.014–1408.014 | `bba0ec4d1a99aa08…` | ≈106.9s |
| `04_phase5_p1_polish`（已验收 V3-R P1） | polish | **1325.123–1347.123** | `f259da7bbb6fd9c5…` | ≈**94.9s** |
| V3-A `best_round=0` 重跑 | 继承 raw | 同 raw | = raw | ≈106.9s |
| V3-A `best_round=1` | 在 raw 上增量 | 1382–1412 **双 opening** | `045586fe44a84ac3…` | ≈160.9s |

`self_revise_summary.json` 实证：

- `phase5_dir` = `…/04_phase5`（**不是** `04_phase5_p1_polish`）
- `source_sha256.edl` = `bba0ec4d1a99aa08…`（raw）
- 源视频相同：`/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4`

**为何「无修订」仍差于已验收 V3-R？**  
无修订时 Agent **原样保留输入基线**。评测喂入的是 raw `04_phase5`，不是 P1 polish；因此 `best_round=0` 只能等于 raw，**不可能**保持 polish 成片。这是基线选择错误，不是「超时逻辑改坏了 polish」。

另外，`best_round=1` 在错误基线上又 `search_add` 出同义 `_live` 重复镜头，并把进球窗扩到未核验区间（含 go-ahead `SUSPECTED_REPLAY`），造成进一步退化。

---

## 2. 退化相关代码位置（修复前）

| 位置 | 问题 |
|------|------|
| `run_self_revise` 直接使用 `--phase5-dir` | 无 sibling `04_phase5_p1_polish` 解析；默认评测易踩 raw |
| `apply_candidate_revision` `search_add` | 不检查同 canonical role / 高重叠窗，可插入 `*_live` 双胞胎 |
| `apply_candidate_revision` `replace` | 旧段可能仍 `include_in_cut=True`；未阻止 NOT_VERIFIED 扩窗替换 |
| `important_segments_regressed` | `agent_bound=True` 即可豁免媒体漂移 |
| `build_bound_segment_from_observations` | `NOT_VERIFIED` 仍写 `is_replay: False`（伪非回放） |
| `decide_accept` | 重复镜头 / 新增 `SUSPECTED_REPLAY` 仍可走 `quality_improvement` |
| `quality_audit.evaluate` | 无相对 V3-R 非退化、无同 role 意外重复检测 |

---

## 3. 修复内容（本分支）

1. **`resolve_phase5_baseline`**：若请求 `04_phase5` 且存在 sibling `04_phase5_p1_polish`，默认切到 polish；`--no-prefer-p1-polish` 可关。写入 `baseline_resolution.json` + summary。  
2. **`search_add`**：同 canonical goal role 已有有效窗 → 拒绝；高重叠同样拒绝。  
3. **`replace`**：退休同族旧段（`include_in_cut=False`）；无 first-live 核验时禁止扩窗替换已有有效非回放进球。  
4. **`important_segments_regressed`**：不再因 `agent_bound` 豁免；重复 goal cut 记回归。  
5. **`build_bound_segment_from_observations`**：`is_replay=None`（未知），保留 `NOT_VERIFIED`。  
6. **`decide_accept`**：拒绝重复 goal / 带 `SUSPECTED_REPLAY` 的自动质量接受。  
7. **`quality_audit`**：同 role 重复、重叠窗、相对 baseline 漂移；`baseline_edl` 可选传入。

---

## 4. 验证（全离线）

```text
PYTHONPATH=algo:. python -m unittest tests.test_v3a_p0_no_regress tests.test_v3a_general_agent -v
→ 17 OK
```

| 用例 | 结果 |
|------|------|
| A 无修订 → EDL ≡ polish | PASS |
| B 已有 opening 再 search_add → 不重复 | PASS |
| C 无强证据扩窗 replace → 拒绝 | PASS |
| D replace 后旧段出 cut | PASS |
| E degraded/超时风格 → 保留 polish，无假改善 | PASS |
| F 缺 opening 时 search_add 仍可绑定 | PASS |

**未做：** 新的付费 API 三轮；**未宣称**新成片「质量优于」人工看片验收——本次修复后 offline 候选与 polish **EDL 恒等**，MP4 为 polish 副本对照。

---

## 5. 产物路径

- 修复后 offline 输出：  
  `/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/v3a_p0_fix_offline_20261105/`
- 候选 MP4（= P1 polish 副本，EDL 一致）：  
  `…/v3a_p0_fix_offline_20261105/v3a_candidate_render/story_clean.mp4`
- V3-R polish 对照：  
  `…/04_phase5_p1_polish/story_clean.mp4`
- 退化样例（旧评测，勿当基线）：  
  `…/v3a_cross_match_3round_20261104/v3a_candidate_render/story_clean.mp4`

### 修复前后 EDL（摘要）

- **前（best_round=1）：** 11 行；opening 双段 1382–1412；eq/ga 扩窗未核验  
- **后（offline 无修订）：** 9 行；与 polish 一致（opening 1325–1347 等）

---

## 6. 未解决问题

- Planner API 超时仍会导致 degraded 空转（基础设施），本 P0 只保证 **不假改善、不丢正确基线**。  
- `FIRST_LIVE_VERIFIED` 完整核验链仍未接通；禁止伪 live 不等于已证明首播。  
- B 场亦有 `04_phase5_p1_polish`：默认 prefer 会改变其评测基线，需在后续跨场复测中显式记录 `baseline_resolution`。  
- 视频级人工再验收未在本任务重做（EDL 恒等 polish 时可复用原 polish 观感结论）。

---

## 7. Git

修复提交见分支 `story-va-v3-a-p0-no-regress`（本文件同提交）。冻结 `story-va-v3-a` @ `e92070f` 未改。
