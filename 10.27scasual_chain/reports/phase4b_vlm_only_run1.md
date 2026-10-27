# Phase 4B 首次真实 VLM-only 联调结果（已停止，无第二轮）

**分支**: `story-va-phase2c` @ `26f5e9e`  
**授权范围**: 1 次 · equalizer_only · HTTP≤3 · tokens≤256 · cost estimate ≤$0.10  
**真实 API 是否调用**: **是（尝试了）** · **成功响应: 0**

## 结论（先答重点）

1. **Qwen 没有真正识别到目标足球场景。** 三次 vision HTTP 均 `URLError`，无 Token、无结构化观察；随后进入 `degraded`，标签为 `uncertain`。
2. **没有足够证据定位扳平进球。** 本地抽到的 2 帧是克罗地亚vs加拿大直播画面（比分仍 **0–1**，时钟约 35:46 / 35:58），属于窗口边缘的攻防/倒地镜头，**未见清晰射门入网或庆祝**；候选窗未调整；`render_ready=false`。
3. **未扩大额度、未开第二轮、未调 Planner、未搜 go_ahead。**

## 实际请求 / 费用

| 项 | 值 |
|----|-----|
| HTTP attempts | **3**（达上限后停止） |
| real_ok | **0** |
| real_failures | **3**（皆 `URLError` / `transient_error`） |
| degraded_calls | 1（不计 HTTP） |
| prompt/completion tokens | **0 / 0** |
| est_cost_usd_real | **0**（估算；不以发票为准） |
| model | `Qwen3.6-Plus` |
| roles | vision only |

门禁：`max_calls=3`、`max_cost_usd=0.10`、`max_completion_tokens=256` 全程生效。

## 抽帧与媒体时间（成功）

| frame_id | requested | actual |
|----------|-----------|--------|
| `f_0000_3059953` | 3059.953s | **3059.96s** |
| `f_0001_3071853` | 3071.853s | **3071.86s** |

- seed center **3065.903s** · window **3059.903–3071.903** · 用帧 2/4  
- 人工看帧：CCTV 4K 直播角标；比分 **克罗地亚 0–1 加拿大**；未见图板上扳平  
- Qwen 原始观察：**无**（失败消息 `URLError`）

## 与 Mock 对比

| | Mock Phase4A | 本次 Real |
|--|--------------|-----------|
| provider_mode | mock | degraded（real 失败） |
| labels | 伪 `goal`/`shot` | `uncertain` |
| 窗口调整 | 有（假阳性驱动） | **无** |
| equalizer media | 可被 mock 挪窗 | 仍为 plan 原窗 3061.903–3073.903 |
| 可信度 | 不可信 | 无 VLM 证据 |

## 门禁保持

- go_ahead_goal：`pending` / `media_in=null` / blocked  
- `render_ready=false` · `render_ready_edl` 空  
- 观察未 promote；未跑 `final`

## 产物路径

- 实验报告: `_local_render/phase4a_real_vlm1/phase4a_experiment_report.json`
- Plan/EDL: `_local_render/phase4a_real_vlm1/croatia_plan_phase4a.json`
- Preview: `_local_render/phase4a_real_vlm1/croatia_preview_v2.mp4`
- Contact sheet: `_local_render/phase4a_real_vlm1/review_v2/contact_sheet.jpg`
- 抽帧: `_local_render/phase4a_real_vlm1/frames/`
- 分析摘要: `reports/phase4b_vlm_only_run1_analysis.json` · 本文件

## 失败原因与下一步（需新授权）

联调进程内对 `llmapi.paratera.com` 出现 **URLError**（3 次耗尽额度）。事后在无沙箱网络下 DNS/TLS 正常，且 `GET /v1/models` 返回 200——偏向**运行时出网/解析不稳定**，不是模型 ID 配错，也不是预算门禁失效。

建议（**不自动执行**）：

1. 用相同 caps 再授权 **1 次** `--real`（在稳定出网环境），确认 Qwen 多模态 POST 可达。  
2. 若通了仍认不出进球：中心 **3065.9s** 附近加密抽帧（仍控制 HTTP≤3），因当前 2 帧落在窗两端且比分仍为 0–1。  
3. **不要**把 Mock 的 goal 标签当事实；**不要**扩大到 go_ahead / Planner。

## 4B.1 根因补记

见 `reports/phase4b1_urlerror_rootcause.md`：首次失败为沙箱/DNS（`full_network` 下 `gaierror`），非模型能力问题。已增强 URLError 分类；**未**自动二次计费。
