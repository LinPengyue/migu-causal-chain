#!/usr/bin/env bash
# 推送到 https://github.com/LinPengyue/migu-causal-chain
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REMOTE="git@github.com:LinPengyue/migu-causal-chain.git"
# 若 22 端口被墙，取消下行注释：
# export GIT_SSH_COMMAND="ssh -p 443 -o Hostname=ssh.github.com"

git remote set-url origin "$REMOTE"

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  gh repo create LinPengyue/migu-causal-chain --public --source=. --remote=origin --push 2>/dev/null || git push -u origin main
else
  echo "请先在 GitHub 创建空仓库: https://github.com/new  名称 migu-causal-chain"
  echo "然后执行: git push -u origin main"
  git push -u origin main
fi

echo "Done: https://github.com/LinPengyue/migu-causal-chain"
