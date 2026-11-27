# V3-R-General C_levante_rayo intake (stop: missing predicted shortchains)

- Branch: `research/sportscausal-template-generalization`
- Freeze: `3720705` (`372070553561a0c56364542c8235ff4ed4985fda`)
- Artifact dir: `research/sportscausal/artifacts/v3r_general_C_levante_rayo/`
- Paid HTTP / Story Agent P1–P3 / A·B rerun / algo·template param edits: **none**
- Evidence→R1→R2a.4→R2bc→R3: **NOT RUN** (blocking inputs missing)

## 1. Source video

| field | value |
|---|---|
| FanEdit Match ID | `FH-35DA83FD` |
| path | `/mnt/data4/migu/10月20日 25-26赛季西甲第9轮 莱万特VS巴列卡诺 国语.mp4` |
| SHA256 | `5ab8ee77ed0d0cb56f020348d4c73b4c27c738f6285db941e1797f87bb1d4d73` |
| size | 5472281362 bytes (~5.10 GiB) |
| duration | 7764.074 s |
| video | 1920×1080 h264, r_frame_rate=50/1, avg=194011/3882 |
| audio | aac 44100 Hz / 2 ch |

Files: `media/sha256.txt`, `media/ffprobe.json`, `media/media_identity.json`, `media/size.txt`.

### Media timeline (from delivery atoms)

- Event time basis: `media_time.event_time_sec`
- First / last event_t: **378.7** / **7548.04** s
- Window span (min start → max end): **360.13** → **7549.26** s
- n_events: 443 (LIVE 372 / REPLAY 71)
- `ignore_segments`: see `media/media_identity.json` (PRE_MATCH + BETWEEN_SEGMENTS + …)

## 2. Annotation / prediction inventory

### Present

| asset | path | notes |
|---|---|---|
| Raw atoms | `causal-chain2/11.23casual_chain/data/交付_out/10月20日_25-26赛季西甲第9轮_莱万特VS巴列卡诺_国语.json` | 443 events; teams 莱万特/巴列卡诺 |
| Human `*_causal.json` | same dir `…_国语_causal.json` | **30** human chains — **forbidden as prediction input** |
| strip_gold / highlight_gold | `…/datasets/matches/10月20日_…_国语/` | **forbidden** as prediction / candidate construction |
| strip_dump (eval) | `…/reports/strip_dump/10月20日_…_国语.json` | mode=`gold_clips`, algo=`causal_chain6`, use_llm=false, **8** gold clips, **6** `all_preds` |
| strip_dump_online | `…/reports/strip_dump_online/…` | mode=`online`, 8 clips vs gold |
| Score path (T01) | prepared → `inputs/C_score_path_from_t01.json` | `0:0 → 0:1 → 0:2 → 0:3` (source `10.27sstory_chain/reports/story_t01/…`) |

strip_dump pred templates observed: `corner_cross_goal`, `outcome_other`, `shot_save_chain`, `turnover_counter_goal` (1×).

### Missing (blocking Evidence→R3)

A/B closed-loop used these; **none found for C** (searched `_story_va_outputs`, sportscausal artifacts, causal-chain2 reinfer products):

1. **`events_enriched.json` + `enrich_report.json`** (A: `closed_loop_*/01_enrich/`)
2. **Full reinfer strip** `mode=reinfer_atom_enriched` (A: `02_strip831/strip_*_original.json`, n_chains≈81)
3. **`predicted_causal.json` with `v3_adapter`** (A: `03_v1_adapt/predicted_causal.json`)

Why gold_clips strip_dump is **not** substituted:

- Eval dump scoped to gold clips, not full-match reinfer.
- 6 preds ≠ A-style ~81 predicted shortchains.
- `evidence_representation.build_evidence` requires a V1-adapter document (`v3_adapter` + `causal_chains`, `is_benchmark_gold≠true`).
- Protocol forbids using human causal / strip_gold / story-chain nodes to manufacture candidates.

## 3. Pipeline decision

Per user rule: *若缺少预测短链或其他必要输入，报告缺失情况，不自行启动付费调用*.

| stage | status |
|---|---|
| Evidence Representation | NOT RUN |
| R1 semantic normalization | NOT RUN |
| R2a.4 causal episode graph | NOT RUN |
| R2b/R2c operators + 8 templates | NOT RUN |
| R3 Story Graph / Initial EDL | NOT RUN |
| turnover_to_goal audit | N/A (no candidates; pipeline not run) |
| Initial EDL render | NOT RUN |

`http_calls=0`. No thresholds / template params changed. No Story Agent. No A/B rerun.

## 4. Commands actually run (intake only)

```bash
cd /data2/lpy1/worktrees/migu-sportscausal-template-gen
git rev-parse HEAD   # 372070553561a0c56364542c8235ff4ed4985fda

sha256sum "/mnt/data4/migu/10月20日 25-26赛季西甲第9轮 莱万特VS巴列卡诺 国语.mp4"
ffprobe -v error -show_format -show_streams -print_format json   "/mnt/data4/migu/10月20日 25-26赛季西甲第9轮 莱万特VS巴列卡诺 国语.mp4"   > research/sportscausal/artifacts/v3r_general_C_levante_rayo/media/ffprobe.json
# + local Python inventory writers (no network)
```

Evidence→R3 CLIs **not** invoked.

## 5. Artifacts

```
artifacts/v3r_general_C_levante_rayo/
  REPORT.md
  media/{sha256.txt,ffprobe.json,media_identity.json,size.txt}
  inputs/{input_inventory.json,C_score_path_from_t01.json}
```

## 6. Unblock checklist (for a later authorized zero-HTTP or budgeted run)

1. Produce C `01_enrich` (events_enriched + enrich_report) without using human chains as **prediction**.
2. Run local `causal_chain6` reinfer strip on enriched events (`use_llm=false`) → full strip JSON.
3. Run existing `v1_causal_adapter` → `predicted_causal.json` (`is_benchmark_gold` false).
4. Then freeze Evidence→R3 into this artifact dir; audit all 8 templates with focus on `turnover_to_goal`; render EDL only if candidates exist.

Do **not** treat this REPORT as quality verification or release authorization.
