# Story-First v2 闭环

使用 `--enable-story-first` 开启。流程为初始 V3-R EDL → 所有相邻语义节点区间 → Generator → Causal-4 → 原 V3-A Planner → 源视频核验 → 临时 EDL → Renderer / 双视频 Verifier → Phase 8 修订反馈。

- 显式 `story_anchor` 成对可用时优先使用。旧 EDL 回退到进球动作节点，并按原剪辑顺序走相邻区间。每个区间最多生成五条，候选 ID 带区间前缀。
- 所有结构合法的候选进入 Planner。数值评分保存在每区间的排名产物。Planner 看到事件、关系、范围、机制解释和不确定性。评分失败时仍可探索结构合法的假设。
- Planner 每轮可选择、拆分或组合候选，返回事件和关系 ID，程序绑定实际 PTS 与插入位置。未通过核验的事件和关系、首次直播状态及全片评价反馈给同一个 Planner。首轮只生成一次，后续复用候选池。
- 同一故事的多个插入作为一次试剪。每个新增窗口需要绑定的上下文评价与 FIRST_LIVE。现有 FIRST_LIVE 连续播出证据协议增加 `STORY_ACTION`，包含动作前、动作、动作后三个阶段，并要求排除更早播出同一动作。进球继续使用原有射门、入网证据协议。源图像核验仍使用有 PTS 和帧引用的抽样，独立的连续播出证明通过 `--first-live-evidence-dir` 提供。
- 正式交付使用现有 Phase 8 最佳版本逻辑。当前双视频 Verifier 的抽帧判断至多支持继续尝试或人工审片。人工承担最终视频质量评价。

## 入口

`story_e2e_cli` 支持用冻结 V3-R 回归。`story_full_e2e_cli` 支持从原始事件和视频起跑。关掉 `--enable-story-first` 即为同输入的对照路径。

离线预检使用 `--enable-story-first --offline`（`story_e2e_cli`），写出区间和模型请求。旧产物可以通过 `--story-first-artifacts-dir` 复用。该参数接受单区间 POC 目录、带 `interval_01` 等子目录的集合，以及历史 `01_generate_max5` / `03_score_real` 布局。复用前重新核对锚点、计划、事件 ID/PTS 和评分文件 SHA。

真实模型运行依赖现有 API 授权与显式预算。`STORY_FIRST_LLM_MODEL` 用于 DeepSeek Flash 候选生成和四维评分。两个有事件的区间从头发现最多用四个文本请求。预算不足时优先覆盖区间，实际覆盖和评分状态见审计。迭代与成片核验也使用同一个请求数、费用和重试控制。多轮使用 `--phase8-paid-multi-round`。

使用 `--build-local-first-live-evidence` 时，遇到缺少首次直播证据的候选会输出对应原片上下文和帧包。该帧包可用于后续独立播出审查。

## Cursor 回归与验收

1. 运行 `tests/test_v3a_story_first_closed_loop.py`、现有 Story-First 专项和 `tests/test_v3a_continuous_broadcast_phase.py`。
2. 用同一比赛的完整输入离线预检。核对 opening→equalizer 旧产物复用、equalizer→go_ahead 的区间及事件量，读取 `story_first/story_first_pool.json`。
3. 经预算授权后进行同输入的开启和关闭对照。预先确认候选源窗口的独立 FIRST_LIVE 证据，有缺口时先保存核验请求和连续原片证据。对照 `story_first_trial.json`、`story_first_feedback.json`、`first_live_window_ledger.json`、临时 EDL、成片和双视频 Verifier 输出。若生成模型在两个独立区间都返回候选，检查 Planner 收到了全部候选且输入没有数值评分。
4. 按同一原始视频对照人工查看试剪，核对新增情节、背景和原有进球。再用其他比赛和故事模板检查覆盖与质量。

本地验证使用模型及正向证据测试夹具。真实比赛的连续播出证明、成片效果和人工对照仍需服务器实片确认。
