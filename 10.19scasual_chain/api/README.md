# 故事链集锦协议层 RC（咪咕 2.3–2.6）

## 联调启动（必须单 worker）

本机需已安装 **Python 3.9+**（包内不带解释器）。首次会自动创建 `.venv-api` 并只装协议依赖（不含 torch）。

- macOS：双击 `start_api.command`（若提示无法打开，在终端执行 `chmod +x start_api.command start_api.sh`）
- Windows：双击 `start_api.bat`
- Linux：`bash start_api.sh`

浏览器打开 http://127.0.0.1:8000/docs ；终端里 Ctrl+C 停止。

手工启动：

```bash
cd 8.31causal_chain
export PYTHONPATH=$PWD/algo:$PWD
uvicorn api.app:app --host 0.0.0.0 --port 8000 --workers 1
```

文档：`api/README.md` · `api/ACCEPTANCE.md` · `api/openapi.json`

## 时间语义（已确认）

| 位置 | 单位 | 含义 |
|------|------|------|
| `eventTime` / callback `start`·`end` | **seconds** | 媒体时间轴；原点=输入视频/直播会话 |
| 算法内部 | **milliseconds** | 仅 `api/adapters` 用 Decimal 转换 |

## chainType

- 1～18：`MIGU_CHAIN_TYPE_MAP`（算法模板）
- **19**：`MIGU_REEL_CHAIN_TYPE` 集锦组合链（仅 `highlightType=5`，非算法模板）
- 三个新增 outcome 细分类 → 18（不得 → 19）

## eventTypeId 映射

**唯一表**：`api/event_type_map.py` → `PROVISIONAL_EVENT_TYPE_MAP`  
禁止其它文件 hardcode。

未知 `eventTypeId`/`eventName`：
- **不**静默映射成 goal/shot 等已知类型；
- 默认写入哨兵类型 `unmapped`，日志含 `taskId/matchId/clipId/eventTypeId/eventName`；
- 可选 `unknown_event_type_policy=reject` 直接拒绝 sync。

### 唯一剩余协议待确认项

> **正式 `eventTypeId → internal type` 字典**（咪咕书面版）。到位后只替换 `event_type_map.py`。

不扩展 `attributes` 字段。

## 2.6 时机与幂等

- 1～4：sync 闭合或 media deadline timer；`emitted_result_ids` 去重
- 5：end 后真实 causal_chain8 reel → type5/19；`type5_emitted` / `type5:reel` 防重复 end
- end 先 `cancel_timers` 再 flush，避免 timer 与 end 双发
- callback HTTP 重试不新增业务 result id

## 测试

```bash
export PYTHONPATH=$PWD/algo:$PWD
python -m pytest api/tests -q
```
