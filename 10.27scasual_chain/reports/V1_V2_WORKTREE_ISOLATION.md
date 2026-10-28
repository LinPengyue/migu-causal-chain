# V1 / V2 工作目录与产物隔离

## Worktrees

| 角色 | 路径 | Git 定位 |
|------|------|----------|
| **V1（只读算法基线）** | `/data2/lpy1/worktrees/migu-story-va-v1` | 分支 `story-va-v1-baseline`，算法以 Tag `story-va-v1.0-structured-baseline` = `462ea11` 为准 |
| **V2（视频驱动开发）** | `/data2/lpy1/worktrees/migu-story-va-v2` → `/tmp/migu-va2c` | 分支 `story-va-video-driven` |
| 主仓（勿混跑故事实验） | `/data2/lpy1/causal-chain2` | `main`（本封版**不**合并 main） |

```bash
# 查看
git -C /tmp/migu-va2c worktree list

# 恢复 V1 到纯 Tag（丢弃说明分支上未推送的本地改动时慎用）
# git -C /data2/lpy1/worktrees/migu-story-va-v1 fetch --tags
# git -C /data2/lpy1/worktrees/migu-story-va-v1 checkout story-va-v1.0-structured-baseline
```

**规则：**

1. 不要在同一目录 `git checkout` 在 V1 Tag 与 V2 分支间来回切。
2. V2 **禁止**直接改 V1 worktree 内文件；复用 Composer/Renderer 时在 **V2 分支** 复制或适配。
3. 不删除 `story-va-phase2c` / Tag；不 `push --force` Tag。
4. 不向 Git 提交 API Key / `.env`。

## 产物与缓存隔离

| 用途 | V1 | V2 |
|------|----|----|
| 新运行输出 | `/data2/lpy1/_story_va_outputs/v1/` | `/data2/lpy1/_story_va_outputs/v2/` |
| 成片预览 | `/data2/lpy1/_story_va_previews/phase5/`（已冻结四场，勿覆盖法国 first-run 语义） | `/data2/lpy1/_story_va_previews/video_driven/` |
| 报告（仓内） | `…/reports/phase5/` @ Tag | `…/reports/video_driven/` on V2 |
| 原始 MP4 | `/mnt/data4/migu/` **只读共享** | 同左 |

## 确认项

- [x] V1 Tag 已推送，SHA = `462ea11`
- [x] V1 worktree 无 `video_only_*` / `global_video_index` 等 V2 模块
- [x] V2 worktree 含 video-driven 代码，与 V1 目录分离
- [x] 输出根目录 `v1` / `v2` 已创建
