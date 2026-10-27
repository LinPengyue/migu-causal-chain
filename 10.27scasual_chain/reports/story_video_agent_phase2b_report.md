# Story Video Agent Phase 2B — 远程 LLM/VLM API 感知闭环

## 交付取向
咪咕最终方案采用**远程大模型 API**（OpenAI-compatible Chat Completions），不以本地部署大模型为生产路径。  
规则策略保留为 dry-run / API 失败降级。

## 能力
| 模块 | 作用 |
|---|---|
| `api_provider.py` | Planner / Vision 独立 endpoint、超时重试、RPM 限流、Token/成本统计、响应缓存 |
| `vision_provider.py` | 帧图 → 结构化 JSON；程序绑定 PTS；模型时间字段剥离 |
| `agent.py` | LLM Planner 决策 + 规则 fallback；`Planner→Tools→VLM→Memory→Planner` |
| `frames.py` | 真实 PTS（`pts` / `requested_only`）；关键进球窗优先预算 |
| `memory.py` | sampled / observed / unresolved；禁止 VLM 升格 verified |

## 环境变量
```
STORY_API_ENABLE=1
STORY_LLM_BASE_URL / OPENAI_BASE_URL
STORY_LLM_API_KEY  / OPENAI_API_KEY
STORY_LLM_MODEL
STORY_VLM_BASE_URL / STORY_VLM_API_KEY / STORY_VLM_MODEL
STORY_API_SMOKE=1   # 仅 unittest 真实 smoke
```
未配置密钥或未开 `STORY_API_ENABLE` → mock，**不计费**。

## 测试
`unittest test_dry_run + test_media + test_perception` → **24 OK（1 skip smoke）**

覆盖：PTS≠requested、非零 start、预算优先级、法国三任务 mock 闭环、克罗地亚 setup 主动搜索、dry-run/media-only 回归、API smoke 门控跳过。

## 法国 / 克罗地亚
- 法国：`--france-focus` 仅扳平动作 / 反超动作 / 反应；mock 感知可跑通 evidence JSON + frame_id 绑定。
- 克罗地亚：`--croatia-setup-focus` / `missing_setup_visual` 一层 coarse，预算内停止。
- 本机未配置付费 API，未发起真实计费调用。

## 非范围
无 Editor / RSI 自进化 / Gate；不训练、不下载大模型；不改 T01 规则结论。
