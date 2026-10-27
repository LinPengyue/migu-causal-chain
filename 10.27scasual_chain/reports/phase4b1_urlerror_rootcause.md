# Phase 4B.1 URLError 无计费排障报告

**分支**: `story-va-phase2c`  
**约束**: 未调用 `/chat/completions` · 未发起第二次真实 VLM · 未扩大 HTTP/Token/费用门禁

## URLError 根因（明确）

第一次真实联调在 **Cursor Agent 沙箱网络** 下执行（`full_network` 仍受限）。在同一 Python（`/home/anaconda3/bin/python3` 3.9.7）下复现：

| 环境 | DNS | TCP:443 | TLS | GET `/v1/models` | 说明 |
|------|-----|---------|-----|------------------|------|
| 默认沙箱（有 `https_proxy=http://127.0.0.1:46069`） | ❌ `gaierror` | 跳过 | ❌ | ❌ `URLError` reason=`OSError` **Tunnel connection failed: 403 Forbidden** | 代理隧道拒绝 |
| `full_network`（无代理 env） | ❌ `gaierror` Temporary failure in name resolution | ❌ | ❌ | ❌ `URLError` / `gaierror` | **与首次联调同类** |
| `all`（关闭沙箱） | ✅ `115.190.35.43` | ✅ | ✅ TLSv1.3 | ✅ HTTP 200，鉴权看似通过 | 仅证明网络+鉴权，**≠** 多模态推理成功 |

**结论**: 根因是 **Agent 运行时 DNS/出网隔离（及沙箱代理 403）**，不是 Qwen 视觉能力不足，也不是模型 ID / Key 格式错误。旧 `_classify_error()` 只记 `"URLError"`，掩盖了 `gaierror` / proxy tunnel 细节。

层次区分：

1. 网络可达（DNS/TCP/TLS）— 沙箱失败，无沙箱成功  
2. HTTP 服务响应 — `/v1/models` 200（无沙箱）  
3. 鉴权通过 — models 列表可读（无沙箱）  
4. 多模态推理成功 — **尚未验证**（禁止自动二次 `/chat/completions`）

## 修复措施

- `api_provider._classify_error` / `_classify_urlerror`：脱敏记录 `category=dns|proxy|tls|timeout|connection`、`reason_type`、`detail`  
- `failure_status` → `network_dns` / `network_proxy` / …  
- `_sanitize_error_text`：剥离 API Key、Bearer、图片 base64、代理 user:pass  
- 单测：`test_api_error_classify.py`（Mock 注入 + 脱敏；无 chat 计费）

## 抽帧采样（未改全局算法）

`FrameStore.sample_times` 对窗 `[3059.903, 3071.903]`：

| count | 采样点 |
|-------|--------|
| 2（首次） | **3059.953, 3071.853**（两端，**无中心**） |
| 3（建议下次） | **3059.953, 3065.903, 3071.853**（含中心） |

下次真实联调建议：`--frames-per-round 3`，`frame_budget` 仍 ≥3 且 ≤4；HTTP≤3、Token≤256、`MAX_COST_USD=0.10` 不变。

## 产物（已脱敏，无图/视频/Key）

- `reports/phase4b1_network_diag_sandbox.json`
- `reports/phase4b1_network_diag_full_network.json`
- `reports/phase4b1_network_diag_all.json`
- `reports/phase4b_vlm_only_run1.md`（首次实验）
- `reports/phase4b_vlm_only_run1_analysis.json`
- 本文件

## 下一次真实请求（须重新授权，不自动执行）

- 在 **无沙箱 / 可解析 DNS** 的环境执行  
- 仍仅 `equalizer_goal` + `Qwen3.6-Plus`  
- `--frames-per-round 3 --max-rounds 1 --frame-budget 4`  
- HTTP≤3 · completion≤256 · cost estimate ≤$0.10  
- 预计采样：**3059.953 / 3065.903 / 3071.853** s
