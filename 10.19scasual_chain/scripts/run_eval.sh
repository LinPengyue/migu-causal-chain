#!/usr/bin/env bash
# 在 8.31causal_chain 根目录执行（可独立于仓库其它目录）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="${ROOT}/algo:${ROOT}/eval${PYTHONPATH:+:$PYTHONPATH}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
MODEL_PATH="${MODEL_PATH:-./models/Qwen2.5-VL}"
TASKS="${TASKS:-strip,highlight}"

echo "ROOT=$ROOT"
echo "CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
echo "MODEL_PATH=$MODEL_PATH"
echo "TASKS=$TASKS"

# 默认：拆条+集锦；集锦用强制 Qwen（与当前填表口径一致）
# 覆盖示例：TASKS=strip bash scripts/run_eval.sh
#          HIGHLIGHT_LLM_ASSIST=0 TASKS=highlight bash scripts/run_eval.sh
EXTRA=()
if [[ "${HIGHLIGHT_LLM_ASSIST:-1}" == "1" ]] && [[ "$TASKS" == *highlight* ]]; then
  EXTRA+=(--highlight-llm-assist --report-name report_hl_llm_assist.json --reel-dir reels_llm_assist)
fi

exec python -u eval/run_eval.py \
  --use-llm \
  --model-path "$MODEL_PATH" \
  --device cuda \
  --tasks "$TASKS" \
  "${EXTRA[@]}" \
  "$@"
