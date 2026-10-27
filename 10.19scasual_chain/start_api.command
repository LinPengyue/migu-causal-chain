#!/bin/bash
# macOS 双击启动（Finder 打开后会弹出终端）
cd "$(dirname "$0")"
exec bash "./start_api.sh"
