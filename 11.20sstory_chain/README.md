# 足球翻盘 Story Chain

2026-11-20 交付版，基于 [已验收的实现 b5d782d](https://github.com/LinPengyue/migu-causal-chain/commit/b5d782d78cd2081007e892bbede2ee2989289c63)。

本版适用于先落后、再扳平并反超的足球比赛。V3-R 先生成覆盖比分转折的剪辑基线，Story-First 再从相邻故事节点之间寻找铺垫，核验新增素材、渲染试剪并检查剪辑边界。交付目录包含算法代码 `algo/`、拆条适配入口 `eval/strip_adapter.py`、依赖和操作手册。比赛素材由运行方提供。

## 环境准备

使用 Python 3.10 或以上版本，系统 PATH 中需有 `ffmpeg`、`ffprobe` 和 `tesseract`（记分牌 OCR，含 `eng` 语言数据）。

在仓库根目录执行：

```bash
cd 11.20sstory_chain
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export PYTHONPATH="$PWD/algo:$PWD/eval"
python -m story_video_agent_v3.story_e2e_cli --help
```

运行 Story-First 时，按接入方提供的 OpenAI 兼容模型服务配置以下环境变量。VLM 端点和密钥由同一服务提供时可复用文本服务配置。

| 环境变量 | 用途 |
|---|---|
| `STORY_LLM_BASE_URL`、`STORY_LLM_API_KEY`、`STORY_LLM_MODEL` | 文本模型端点、凭据及规划模型 ID |
| `STORY_FIRST_LLM_MODEL` | 候选故事生成模型 ID，使用文本模型端点 |
| `STORY_VLM_MODEL` | 视频和图像核验模型 ID |
| `STORY_VLM_BASE_URL`、`STORY_VLM_API_KEY` | 视觉服务另有端点或密钥时填写 |

## 输入与运行

`MATCH_JSON` 为同场赛事事件 JSON，包含 `events` 列表，推荐保留 `event_id`、事件类型、`media_time`、比分识别、直播或回放上下文及队伍信息。事件媒体时间以原始 MP4 的时间轴秒数为准，沿用仓库首页的[上游事件输入约定](../README.md#三上游事件-json无-causal必填结构)。比赛分钟和媒体时间可能不同。

### 从原片和事件开始

把以下三个路径换成实际值。输出目录请为本次运行单独指定。

```bash
MATCH_JSON='/absolute/path/match.json'
SOURCE_MP4='/absolute/path/match.mp4'
OUT_DIR='/absolute/path/story_first_run'

STORY_API_ENABLE=1 python -m story_video_agent_v3.story_e2e_cli \
  --match-json "$MATCH_JSON" \
  --events-json "$MATCH_JSON" \
  --source-mp4 "$SOURCE_MP4" \
  --run-fresh-v3r \
  --enable-story-first --story-first-outer-rounds 2 \
  --max-rounds 2 --phase8-paid-multi-round \
  --enable-real-api --i-approve-budget \
  --max-calls 16 --max-cost-usd 0.05 --no-smoke-render \
  --out-dir "$OUT_DIR"
```

此命令先跑 V3-R，再尝试最多两轮 Story-First。示例配置的 HTTP 尝试上限为 16，费用阈值按本地配置估算，实际费用以服务账单为准。若只需离线生成 V3-R 基线，保留同一组输入和 `--run-fresh-v3r`，使用 `--offline --max-rounds 1 --no-smoke-render` 并省略 Story-First 和真实 API 参数。

### 复用已有 V3-R 基线

已有同一源片生成的 `04_phase5` 时，使用上一条命令，把 `--run-fresh-v3r` 换成 `--phase5-dir "/absolute/path/04_phase5"`，并把 `--events-json` 指向同次运行的 `01_enrich/events_enriched.json`。基线目录需有 `story_plan.json`、`candidate_edl.json` 和 `story_clean.mp4`，如有 `t01_story.json` 一并保留。命令中的 `--match-json` 和 `--source-mp4` 仍指向同场原始输入。

比分采样稀疏时，V3-R 可以回查到上一次旧比分观测，从已有事件中定位唯一的非回放首球候选。要让历史比赛应用这项修正，使用 `--run-fresh-v3r` 在新输出目录重建基线。原运行使用因果链补充原子事件时，重建时用 `--causal-atoms-json` 指向同一标注文件。

## 查看产物

| 路径（相对 `OUT_DIR`） | 内容 |
|---|---|
| `01_initial_story/story_clean.mp4` | V0，进入 Story-First 前的基线 |
| `story_first/story_first_pool.json` | 各搜索区间与候选故事 |
| `02_round_01/story_first_trial.json` | 第一轮试剪方案与 P2 核验结果 |
| `02_round_01/story_first_p3/p3_revision.json` | 第一轮 P3 记录，含选定预览的 `selected_preview_mp4` |
| `story_first_outer/story_first_outer_comparison.json` | 第一轮接受后生成，列出各版本 MP4 路径、时长、哈希及外层轮次状态 |
| `story_e2e_audit.json`、`99_final/delivery_status.json` | 执行审计与正式交付状态。正常走完门禁时另有 `99_final/release_gate.json` |

优先打开对照 JSON 中的 `selected_preview.mp4`。若首轮未接受且未生成对照 JSON，可查看 `story_e2e_audit.json` 及第一轮的核验或渲染记录，继续使用 V0 基线。

## 本版验收

阿联酋对阿曼、奥萨苏纳对塞尔塔、法国对澳大利亚、克罗地亚对加拿大已记录 V0、V1、V2 预览对照。克罗地亚用本版复用已通过 P2 的候选完成实片续跑，两个 3:1 裁切窗口均保留，剪辑单跳过中间 0.9 秒坏帧。历史验收为试剪预览，`release_authorized=false`。[克罗地亚实片验收报告](https://github.com/LinPengyue/migu-causal-chain/commit/7235ca7f326cefba8853867c64ca6fee5956c60d)
