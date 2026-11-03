# P3 泛化：克罗地亚 vs 加拿大

**冻结 Commit:** `2d1ec9c`（未针对本场改代码/硬编码）  
**付费 API:** 0  
**success_claimed / render_ready:** false  
**人工原子补全:** 是（`enrichment.provenance=causal_atom_fill`）；**不宣称全自动检测**

## 选型

| 项 | 值 |
|----|----|
| 比赛 | 2022-11-28 克罗地亚vs加拿大 |
| 理由 | 交付有 events+causal；`/mnt/data4/migu` 有原片；score_path 具备 0:1→1:1→2:1… 逆转；**未出现在 V3 plan2 调试目录** |
| 备选未选 | 法国vs澳大利亚（同样有片，但长期作 V1/V2 基线；本轮优先未进 V3 调试的克加） |
| 阻塞项 | 无（视频/数据齐全；无付费 API 依赖） |

## 流水线产物

- 输出根：`/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_C_croatia_canada/`
- enrich：35 atoms（Goal LIVE 5 / REPLAY 0）
- 8.31：61 chains（outcome 极少；goal 终端多来自原子适配）
- MP4：`04_phase5/story_clean.mp4`

## 逐段 QC（关键）

| 段 | 锚点 | LIVE/破门 | 判定 | 证据 |
|----|------|-----------|------|------|
| 失球 opening | 980 | LIVE 直播标；01:06 攻门→庆祝 | **PASS** | `C_croatia/opening/t980.jpg` `t988.jpg` |
| 扳平 equalizer | 3065 | LIVE；35:52 射门在空中（板仍 0:1 滞后） | **PASS**（板滞后） | `equalizer/t3066.jpg` |
| 反超 go_ahead | 3523 | LIVE；1:1 拼抢→庆祝 | **PASS** | `goahead/t3524.jpg` `t3530.jpg` |
| 扩大 3:1 | 6317 | LIVE 庆祝（板 2:1 滞后） | **PASS** | `extend1/t6320.jpg` |
| 扩大 4:1 | 7747 | LIVE 93:24 攻门过程（板 3:1） | **PASS（弱）** | `extend2/t7747.jpg` |
| 原子 Goal@2451 | 2451 | LIVE 但画面为 0:1 进攻，**非破门**；未进 score_path/EDL 动作 | **UNRESOLVED**（原子噪声；故事未误用） | `orphan_2451/t2451.jpg` |

## 因果链 / 覆盖

| 检查 | 状态 |
|------|------|
| 事件补全 Goal 覆盖 | 5 LIVE Goal 原子注入 | 
| 8.31 outcome 链覆盖全部进球 | **UNRESOLVED/弱**（strip outcome 很少；V1 主要靠原子 Goal 进故事） |
| T01 最后落后弧 | 0:1→1:1→2:1 + lead extends | **合理** |
| 故事完整性 | 失球→扳平→反超→扩大 | **基本完整** |
| 无关/重复镜头 | 未见 B 类重复蓄力 | PASS |

## 总判定

- **可跑通冻结流程**，出候选 MP4。  
- 关键进球窗视觉 **大体 PASS（LIVE）**。  
- **不通过终验**：8.31 对进球 outcome 覆盖弱；存在错误 Goal 原子@2451；`render_ready=false`。  
- **非 BLOCKED**（数据与视频足够；无模拟冒充）。
