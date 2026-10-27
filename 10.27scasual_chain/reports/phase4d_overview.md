# Phase 4D 总览 — 动态搜索接入 / 独立核验材料 / 成片准备

基准: `b37a0b0` → 本提交 · **无付费 API** · **`render_ready=false`** · 未合并 main

## 交付

1. 动态种子接入：`resolve_seed_targets` / CLI `--causal-json` `--seed-mode`
2. 独立核验待办包：`phase4d_verification_packets.json`（**未**自动签发）
3. 五段剪辑质量检查：`phase4d_cut_quality_checklist.json` + 下文
4. Candidate EDL / Plan：`phase4d_croatia_*.json`
5. 完整预览（本地）：`_local_render/phase4d/croatia_preview_phase4d_full.mp4`（gitignore）

## 关键剪辑改进

| 项 | 4C | **4D** |
|----|----|--------|
| 蓄力 | 3055–3064.5（9.5s） | **3038–3064**（角球→禁区，~26s） |
| 反超记分牌 | score_path 3697（Δ≈172s） | **视觉 2:1 @≈3600**（Δ≈75s） |
| 收尾 | event_ms 7942 庆祝 | **FULL TIME 4-1 @≈7935** |

停止：不启动付费 VLM，不 merge main。
