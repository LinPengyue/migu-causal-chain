# Phase 5.1 修复与视频审核说明

**分支：** `story-va-phase2c`  
**相对基准：** `082ff08`  
**门禁：** 无付费 API · `render_ready=false` · 不合并 main

---

## 1. 测试数据更正

| 角色 | 比赛 | 状态 |
|------|------|------|
| M0 回归 | 克罗地亚 vs 加拿大 | ✅ 可跑 |
| A 首迁 | 阿联酋 vs 阿曼 | ✅ 可跑 |
| B 冻结验证 | 奥萨苏纳 vs 塞尔塔（主角 **塞尔塔 / right**，最后一次落后弧 1:2→3:2） | ✅ 可跑 |
| C 待传 | **法国 vs 澳大利亚**（上传中：`/mnt/data4/migu/.2022年11月23日 法国vs澳大利亚.mp4.*`） | ⏸ **未完成传输，不得宣称验证完成** |

**更正：** 第四场不是卡塔尔–阿联酋。卡塔尔场 `no_comeback` **不计入**本阶段正例泛化。  
法国场标注已在仓库（`交付_out` / `story_t01`，T01=`story`，主角 left）；**仅等 MP4 传完后**再盘点文件名并零修改跑通。

---

## 2. ChatGPT 克罗地亚问题 → 通用修复

| 问题 | 修复（通用，非场次硬编码） |
|------|---------------------------|
| 3:1 花屏避让裁到入网前（出点 6315.8 < 入网 ~6318.5） | `apply_glitch_avoidance(must_cover=goal_anchor)`：优先保留进球锚点；无法同时避坏帧则 `goal_action_complete=false` + 补证，不得标完整进球 |
| 4:1 无进球动作 | 因果链无 live 进球 → 保持 `missing_live_goal_action:lead_extend_2`；仅短比分牌，**不伪装成进球动作** |
| 收尾出现西班牙–德国等其它转播 | 终场门禁：优先 `ending_final_scoreboard`；`比赛结束` 仅当紧邻终场比分（≤45s）才采用；克场 match_end Δ≈87.8s → **拒绝** |

质量门禁已写入 composer / delivery：

1. 进球剪辑窗必须覆盖进球锚点（事件 `t_sec`）。  
2. 花屏避让不得破坏核心事件；否则缺口+补证。  
3. 终场不得仅因 match_end 标注远切。  
4. 只有比分牌 ≠ 完整进球动作。

---

## 3. A/B 初审与 QC

- 阿联酋–阿曼、奥萨苏纳–塞尔塔：翻盘事件结构有迁移价值。  
- 已生成镜头级 QC 证据包（抽帧，**不声称语义通过**）。  
- 奥萨苏纳摘要明确：**塞尔塔最后一次落后弧**主线，非整场所有进球默认全收。

---

## 4. 其它 5.1 项

- Story Graph：补齐 `event:` 节点；边端点校验；`semantic_verified` 不伪造；单测覆盖。  
- `story_summary.md`：甲方可读正文 + 技术附录。  
- `story_clean.mp4`：比赛画面无「候选审核样片」等技术烧录；说明见 `REVIEW_NOTE.txt`。  
- `story_qc.mp4`：保留技术叠字；与 clean **同一 EDL**。

---

## 5.1b 追加（ChatGPT QC 复审后）

| 问题 | 通用修复 |
|------|----------|
| 进球窗含锚点但仍缺射门前动作 | `goal_action_complete` 拆为 result/approach/context/glitch_break；坏帧前后 **分段** 保留进攻上下文，不播坏帧 |
| 终场=最后比分牌 / 45s 误拒 | match_end 作 **未核验候选**（可远于 45s，有上限）；成片默认 **故事收束包装**，`full_time_verified=false` |
| 多次领先场次范围不清 | `story_scope.json`：全场比分 vs 最后落后弧 vs 弧前省略转折 |

法国–澳大利亚仍为待传保留测试，未针对性调参。

---

## 6. 交付路径（重跑后）

```
_local_render/phase5/{croatia,uae_oman,osasuna_celta}/
  story_clean.mp4  story_qc.mp4
  story_summary.md story_graph.json candidate_edl.json
  REVIEW_NOTE.txt  qc_pack/
/data2/lpy1/_story_va_previews/phase5/*.mp4
reports/phase5/{croatia,uae_oman,osasuna_celta}/   # 同步文本产物
```

法国场：传输完成后另跑，本提交**不**包含其成片验证。
