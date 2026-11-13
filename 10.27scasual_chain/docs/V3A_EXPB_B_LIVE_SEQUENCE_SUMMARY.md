# Exp B — B 场首次直播进球业务时序验证（零付费）

- Branch: `story-va-v3a-p17-native-broadcast-observer`
- Base: `ce897fc` → this docs commit
- Paid HTTP: **0**
- Verdict: **`INSUFFICIENT_EVIDENCE`**
- **`FIRST_LIVE_VERIFIED`**: false（本结论 ≠ FIRST_LIVE）
- EDL / BEST: **未修改**；Stage1–7: **未重跑**；未写入 B 特化算法参数

## 已执行的验证

1. 读取原始 `events.json`（SHA 记入 JSON），按 `media_time.{event,start,end}_time_sec` 排列。
2. 诊断窗口（仅本场审计，不固化进通用算法）：`[6380,6447]` / `[6447,6465]` / `[6465,6550]`。
3. 复用同日 P17.2 源片 SHA `a66147f7…`、P15.3 Stage3 帧字节+PTS 复验状态，以及既有 Stage3–7 产物与仓库内 server-verify 文档。
4. 每条判断标注证据类别：`RAW_EVENTS_JSON_LABEL` / `MODEL_INFERENCE_ON_SPARSE_JPEG` / `PRIOR_ALGO_*` / `DIRECT_FILE_HASH`。

## 关键事实（标签 / 产物，非新视觉观察）

| 项 | 内容 | 类别 |
|---|---|---|
| Stage3 锚点 | Qwen3.6 shot **6447.2** / net **6450.6**；Qwen3.7 shot **6447.88** / net **6450.6**；`live_or_replay=live` | 模型推断（稀疏 JPEG） |
| 原片绑定 | P15.3 `stage3_source_frame_binding_valid=true` | 直接哈希/复解码 |
| 缺陷 | `goal_coverage_01_to_11` | 既有诊断 |
| 标注空洞 | `ignore_segments` **`BETWEEN_SEGMENTS` [6412.5, 6532.7]** 覆盖整个 shot/net；动作窗 **0 条**事件 | JSON 忽略段 |
| 窗内事件 | 进球前 3 条防守（`event_000634`–`636`，比分标签 0:1）；进球后自 `event_000637`@6535.62 起（比分标签 1:1） | JSON 标签 |
| 比分标签 | 0:1@6410.07 → 1:1@6535.62（约 net 后 **85s**） | JSON 标签 |
| Stage4 | `timeline_review_status=UNKNOWN` | 既有算法 |
| Stage5 | `SCORE_TRANSITION_INSUFFICIENT_OCR`；strong_before=0；first strong 1:1@**6459.2** | 既有 OCR |
| Stage6 | `NO_EARLIER_PHASH_MATCH_WITHIN_SCANNED_WINDOW` | 既有 pHash |
| Stage7 | 入网后 4 个切镜候选；shot→net 无切镜 | 既有诊断 |
| 6550+ | `event_000642`@6566.81 等 `REPLAY`/`Shot` 标签；**未**绑定为 6447 进球的同一动作回放 | JSON 标签 |

## 六问结论（摘要）

1. **进球前正常推进？** 仅有缺口前的防守标签；缺口内无业务事件 → 标签不足以证明连续直播推进。  
2. **进球后即时庆祝？** 动作窗无事件，无庆祝类标签 → 无法从 JSON 证明即时庆祝。  
3. **后续同动作再出现？** 窗内无回放标签；6566+ 有其他射门回放标签，但不能当作本进球的同动作证明；Stage6 负匹配 ≠ 首次直播。  
4. **比分与进球时间一致？** 标签换分过晚；OCR 仅有入网后强读数、入网前不足 → 不一致/证据弱。  
5. **庆祝先于进球？** 未发现 `[6380, shot)` 庆祝类标签 → **未**构成标签级回放疑点（也不构成 LIVE 证明）。  
6. **时钟/切镜/开球？** Stage4 UNKNOWN；Stage5 OCR 不足；Stage7 仅有切镜候选 → 不能认证首次播出。

## 支持 vs 反对（相对「直播序列假说」）

**偏向支持但不够证明：** Stage3 双模型 shot/net + live 声称（模型）；P15.3 帧绑定；缺口前无庆祝标签；Stage6 扫描窗内无更早 pHash 命中；Stage7 射门–入网无切镜。

**阻断 / 反对升格：** 标注空洞吞掉进球动作；比分标签与 net 时间绑定弱；Stage4/5 拒绝升格；无连续原片相位观察；无独立「更早同动作」排除；后续 REPLAY 射门未绑定本进球。

## 未验证的推断（禁止当作已证）

- 将 JSON `broadcast_phase=LIVE` / `is_replay` 当作视觉事实  
- 将 Stage3 `live` 当作 FIRST_LIVE  
- 将「无回放标签 / 无 pHash 命中」当作首次播出  
- 将 OCR/标签比分变化当作已认证记分牌事实  

## 最小改进（不新开模块）

优先复用：`native_broadcast_observer`（需先解决单次 HTTP 主链）、既有 Stage5 OCR、P16 `continuous_broadcast_phase` 门禁（不改门禁逻辑）。  
缺失视觉信息：连续原片相位观察、可复现的入网前记分牌/时钟、独立同动作早发审查。

## 产物

- 仓库：`docs/V3A_EXPB_B_LIVE_SEQUENCE_SERVER_VERIFY.json`（本摘要）  
- 可复现命令：`docs/V3A_EXPB_B_LIVE_SEQUENCE_REPRO.sh`  
- 本机完整窗内事件表：`/tmp/lpy1_v3a_p17_expB_live_sequence_20261113/expB_live_sequence_audit.json`
