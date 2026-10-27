# 咪咕验收对照 · 故事链集锦 RC

| 验收项 | 接口 | 状态 |
|--------|------|------|
| 2.3 启动集锦任务 | `POST /highlight/start` | 就绪 |
| 2.4 结束集锦任务 | `POST /highlight/end` | 就绪（flush 1～4 + type5/19） |
| 2.5 拆条内容同步 | `POST /highlight/sync` | 就绪；`eventTime`=媒体秒 |
| 2.6 集锦反向通知 | 出站 `POST {callbackUrl}` | 就绪 |

## 时间

- 外部 `eventTime` / `start` / `end`：**媒体时间轴 seconds**
- 内部算法：**milliseconds**（adapter Decimal 转换）

## chainType

- `highlightType` 1～4 → `chainType` 1～18
- `highlightType` 5 → `chainType` **19**（集锦组合链，`MIGU_REEL_CHAIN_TYPE`）

## 输入字段（不扩展）

`clipId`, `videoPath`, `eventName`, `eventTypeId`, `eventTime`, `score`

## 唯一剩余协议待确认项

正式 **eventTypeId → internal type** 字典。  
当前 provisional 唯一表：`api/event_type_map.py`。未知类型 → 哨兵 `unmapped` + 结构化日志（不静默当成已知事件）。

## 启动

```bash
export PYTHONPATH=$PWD/algo:$PWD
uvicorn api.app:app --host 0.0.0.0 --port 8000 --workers 1
```
