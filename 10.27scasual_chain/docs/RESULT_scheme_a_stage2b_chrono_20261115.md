# Scheme A Stage2b — chrono/team 提示后重跑（2026-11-15）

HEAD: `f4f753011cd7079fb365a057ebc17e5fd0d21a91`  
Out: `/tmp/lpy1_scheme_a_stage2b_chrono_20261115/`  
Pytest: **47 passed**（story_first scheme_a / adapter / poc）  
HTTP: 生成 1 + 评分 1；无 VLM / 未改 EDL / 未进 Planner。未覆盖历史产物。

## 费用

| 步骤 | prompt | completion | est_usd |
|------|-------:|-----------:|--------:|
| 生成 max5 | 64393 | 586 | 0.010011 |
| 评分 | ~13909 实测 | — | 0.002683 |
| **合计** | | | **≈0.012694** |

请求最多 5 条，模型实际返回并接受 **3** 条（rejected=0），未人工凑数。

## 候选与时序/球队核对

| ID | 机制 | 因果时序 | 支持事件 PTS 递增 | notes 球队标签 |
|----|------|----------|-------------------|----------------|
| H1 | substitution_to_late_penalty_pressure | OK (563→617) | OK | 混用 1队换人 + 2队换人/犯规；含 REPLAY 622 |
| H2 | late_shot_volume_to_equalizer | OK (495→635) | OK | 前三段偏 1队；终点 635 为 **2队拦截** |
| H3 | var_penalty_denial_to_equalizer_momentum | OK (622→635) | OK | 627/635 均为 **2队**；622 REPLAY |

相对上一轮 stage2a：

- **时序倒置**：改善。本轮无再把更早的 `event_000472` 拼进“换人后/晚期势头”支撑；全部因果链 `source_pts < target_pts`。
- **球队归属**：仍有问题。H1 叙事“球队持续进攻”混用双方换人；H2/H3 终点事件 notes 指向 2队动作，评分器已标出与“主队施压”冲突。
- **连续施压证据**：评分仍低（多数轴=1）；未把“连续施压”当作已证实。

## 评分排名（观察先验）

| 序 | ID | priority | 五维 A/I/J/M/E |
|---:|----|---------:|----------------|
| 1 | H2 | 0.2875 | 2/1/1/1/1 |
| 2 | H3 | 0.2875 | 2/1/1/1/1 |
| 3 | H1 | 0.25 | 1/1/1/1/1 |

`selected_for_video_observation`: H2, H3, H1。`planner_eligible` 未开放。

完整 raw / ranking / audit：`docs/artifacts_scheme_a_stage2b_chrono_20261115/`
