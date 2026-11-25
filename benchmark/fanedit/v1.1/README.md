# FanEdit — Paired Benchmark 84 (v1.1-provisional)

用于短程因果链识别及长程故事链生成的统一比赛级标注与诊断性评测包。本版本是结构化、可追溯的评测参考，不是已经逐段人工核验的最终 Gold Benchmark。不得将自检分数写作算法性能。

## 1. 冻结范围与来源

- 84 个逻辑比赛 ID；105 份视频源/标注文件（部分为上、下半场；并非105场比赛，也不保证84场均有完整视频）。
- 25,022 条经 LIVE 元数据和媒体区间筛选的原子事件（含一份独立故事证据使用的备选视频源）。
- 750 条短程因果链；4 大类、18 个定义子类、实际覆盖15个。
- 173 条长程故事链、1,536 个故事证据片段；4 大类、17 个定义子类、实际覆盖16个。
- V5 原始212条故事候选中的32条待核故事被隔离（两份审计表按故事 ID 去重）；另7条属于没有合格短链的两场比赛，未纳入统一集合。无新增故事剔除。
- v1.0 的737条短链仅遍历了 V5 故事证据引用过的源文件，漏掉曼联–布莱顿上半场、切尔西–曼联上半场、水晶宫–曼联下半场。v1.1 将这3个同场、非重复半场纳入原筛选流程，分别新增5、3、5条短链，共750条。84个比赛ID、原737条短链及173条故事链全部保持不变。之前报告的769条没有逐条冻结清单，无法验证，不用于本版本。独立核算105份源文件的4768条原始记录，逐条分类，结果与构建脚本的750条源ID集合完全一致。详见 `recount_audit.json` 和 `recount_all_raw_chains.csv`。
- 原始四份 ZIP 的 SHA256 在 `manifest.json`。`build.py` 可复现构建，输入文件名兼容带 `(1)` 后缀的上传版本。无须第三方 Python 库。

## 2. 文件结构

| 文件 | 内容 | 评测角色 |
|---|---|---|
| `manifest.json` | 规模、类别分布、数据版本哈希、限制 | 冻结记录 |
| `matches.jsonl` / `match_inventory.csv` | 比赛清单、视频源ID、各任务计数、已知开发曝光状态 | 比赛级索引 |
| `videos.jsonl` | 源视频名、原始标注路径、时长、球队、审核范围 | 视频寻址 |
| `atomic_events.jsonl` | 源事件、类型、时间、属性、备注、比分、来源 | 原子事件参考 |
| `event_inputs.jsonl` | 按视频组织的事件输入，不包含链条金标或故事标签 | 推理输入 |
| `causal_chains.jsonl` | 筛选后的750条短链参考 | 评测参考，勿喂给常规预测流程 |
| `story_chains.jsonl` | 173条故事、角色、顺序、片段、证据ID | 评测参考，勿喂给常规预测流程 |
| `taxonomy.json` | 原类别词表（中文，保留原始术语） | 公开任务定义 |
| `quarantine_causal.jsonl` | 94场来源范围内未通过筛选的短链及原因，含回放等 | 不参与评测 |
| `quarantine_story.jsonl` | 32条审计隔离故事+7条不在统一集合的故事 | 不参与评测 |
| `quarantine_events.jsonl` | 统一集合中未通过 LIVE/时间检查的原子事件 | 不参与推理或评测 |
| `story_evidence_only_chains.jsonl` | 可能仅作故事证据、不进入短链评分的源链；本版本为空 | 非短链参考 |
| `validation.json` | 结构验证结果 | 验证记录 |
| `build.py` | 可复现构建脚本 | 数据构建 |
| `evaluate.py` | 一对一匹配诊断评测器 | 评测程序 |
| `example_*_prediction.jsonl` | 由一条真实参考投影得到的格式样例 | 仅测试接口，不是模型预测 |
| `recount_audit.json` | 独立核算汇总、13条新增链的源ID | 审计记录 |
| `recount_all_raw_chains.csv` | 84场4768条源记录的互斥纳入/排除理由 | 逐条审计记录 |
| `evaluation_selftest.json` | 自匹配、空预测、重复预测、排除开发场的自检 | 测试记录 |

所有 JSONL 文件 UTF-8 编码，一行一条 JSON；空文件表示没有该类记录。ZIP 不包含原始视频文件。

## 3. 标注与 ID 协议

- `match_id`: V5 的 FH-ID，数据划分必须按比赛级，不能按故事或视频源随机切分。
- `video_id`: 比赛ID加源档案与文件路径的稳定哈希，精确对应同一媒体文件。不能将不同来源的 event_000001 当作相同事件。
- `event_id`: `video_id:E:原event_id`。事件类型保留人工标注的 `type` 与 `type_zh`。原子事件 ID 与因果链内部节点 ID 通过同一源中的 `bz_id` 唯一映射；原内部时间 `source_chain_t_ms` 只作溯源，不能用于媒体定位。
- `chain_id`: `video_id:C:原annotation_id`；`event_ids` 是有序原子事件序列。`start_sec/end_sec` 为相关事件媒体窗口的最小起点/最大终点。类型使用 `category/subtype`，其他类的 `other_name` 是附加原始描述，不算新增类别。
- `story_id`: 原 V5 ST-ID；`segments` 保留原标注 `order/narrative_role/narrative_function/importance/description`，增加 `video_id`、`event_ids`、`causal_chain_id`（如有）。每片段必须绑定源视频。故事链允许直接引用原子事件或引用短链，不要求所有节点都有短链。
- 时间统一为 **秒，源视频局部媒体时间轴**，不是比赛计时、不是转换后的连续全场时间。跨半场故事按原始片段顺序保存，不人为累加半场时长。若后续获得完整视频的对齐表，另建偏移映射，不覆盖原始时间。

## 4. 筛选与审计

短链仅接受明确非回放且至少含两个不同原子节点和两个不同事件时间的条目；内部节点必须能用唯一 `bz_id` 映射至同源事件；映射的事件必须标记 LIVE、非回放、非慢动作，且无指定回放/历史画面等文字；媒体窗口合法，时序不逆序，事件跨度和证据窗口不超过120秒；类别对必须存在于原18类词表；同源相同类别和有序事件序列去重。以上规则是结构与元数据筛选，不等于语义复核。

已知 V5 问题包括：巴西–瑞士反击标签与任意球组织冲突，以及其他待核故事直接引用的短链；四个被直接引用的待核短链均隔离。哥斯达黎加–德国 3729–4143秒及7878秒后的异常素材区间隔离；威尔士–伊朗6237.1秒起的异常时间区间隔离。利物浦–曼城两个上半场源，短链评测保留事件更密集的旧规源，另一源只供已存在的故事证据，不重复计短链。

**限制：**未找回更早的完整逐条短链审计排除清单，原始标注存在误分类、标注遗漏、时间聚集等风险。当前已知问题有隔离记录，但不能证明其余条目已全部通过语义人工复审。所有短链和故事链均为 `is_benchmark_gold:false`、`first_live_verified:false`，仅用于候选参考诊断。审核者应在原视频中确认首次直播、实际事件、因果类别、故事连贯性、标注完整性；审核结果不能直接由脚本自检代替。未标注的有效情节不是天然负例。

## 5. 使用方式

### 短链预测

读取 `event_inputs.jsonl` 中 `causal_eval_source:true` 的源，按视频调用算法；输出 JSONL，每条预测一个短链，至少包含 `match_id,video_id,category,subtype,event_ids,start_sec,end_sec`。时间窗单位秒，引用输入事件ID。

```bash
python evaluate.py --task causal --pred causal_predictions.jsonl --tiou 0.5 --out causal_scores.json
```

### 故事预测

按 `matches.jsonl` 聚合同场所有源的事件输入、预测短链、视频和公开故事模板/类型定义；输出一条故事一个JSON对象，至少包含 `match_id,category,subtype,segments`。每个 segment 至少包含 `video_id,event_ids,start_sec,end_sec`，按叙事顺序排列。不要以标注故事标题、摘要、真实故事片段或人工短链为常规输入。若使用人工短链或给定真实模板类别，作为单列 Oracle 或 template-conditioned 设置单独报告；给定类型时 Type Accuracy 不适用或仅诊断，不与开放类别预测混比。

```bash
python evaluate.py --task story --pred story_predictions.jsonl --tiou 0.5 --out story_scores.json
```

已知4个开发场可用 `--exclude-known-dev` 排除（法国–澳大利亚、克罗地亚–加拿大、奥萨苏纳–塞尔塔、阿联酋–阿曼）。剩余80场仍是**曝光待核**，不是已证明未见测试集。尚未指定 train/dev/test split；不将同场视频源或故事跨集合划分。

### 指标协议（本包新增的诊断定义，尚未冻结为论文最终指标）

- 时间重叠：同一 `video_id` 下合并区间计算交/并；故事链使用全部片段的区间并集，不用最早至最晚的长跨度替代，不跨视频混算。默认阈值0.5，可调整。
- Precision / Recall / F1：在同比赛中，类别与子类一致且 tIoU≥阈值才允许匹配，一对一最大基数匹配；多余预测不能重复命中同一参考。Macro-F1 按出现于参考或预测的类别对平均。
- Type Accuracy：仅在忽略类型、满足时间条件的一对一定位匹配上统计类别对正确率；同时报告匹配数，避免因定位漏检而虚高。
- Exact Match：类型一致、tIoU≥阈值且有序原子事件ID序列完全相同，按参考总数计召回率。故事的有序事件序列按片段展开，对重复ID保留第一次出现。不是文本逐字匹配。
- Mean tIoU、Mean Event-set F1：在类型匹配对上统计；同时报告总召回，避免只汇报已命中样本。匹配是确定性最大基数，非最大权重求解。
- 人工指标：Narrative Coherence、Story Completeness、Visual Faithfulness、First-live Rate、Human Preference；未实现为自动指标，需实际视频及人工评分。Inference Time/API Cost 由算法运行日志采集，不伪造或从参考推断。

当前因果和故事参考均非穷尽；诊断 P/R/F1 只能衡量对现有候选参考的匹配，不能据此把未标注但合理的故事当作真实错误，也不代表最终论文性能。

## 6. 复现构建与自检

```bash
python build.py --input-dir /path/to/four_zips --output-dir /path/to/rebuilt
```

结构检查包括唯一ID、全部事件引用与视频ID一致、时间窗在媒体范围内、故事短链引用存在、每场具备两类参考。自检用参考投影作为预测时 P/R/F1/EM 均为1；空预测F1=0；重复预测降低精确率；已知开发场排除后80场。它们验证格式与评测器行为，不证明标注正确或模型性能。
