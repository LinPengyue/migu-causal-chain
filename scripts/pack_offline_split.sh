#!/usr/bin/env bash
# 方案一：打包 causal_chain2 + mllms_know 环境 + Qwen2.5-VL，大文件 split 为 <=3.5GB 分卷
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/offline_packages"
CODE_SRC="/data2/lpy1/causal-chain2"
MODEL_SRC="/data2/lpy1/Qwen2.5-VL"
ENV_PREFIX="/home/lpy1/.conda/envs/mllms_know"
SECRET_ENV="/data_vepfs_st_byy_1_002/qinghua/causal_chain2/causal_env"
SPLIT_SIZE="3500M"

mkdir -p "$OUT"
cd "$OUT"

# 避免 conda/conda-pack 走失效代理
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy NO_PROXY no_proxy

echo "==> [1/5] 打包代码 causal_chain2_code.tar.gz"
if [[ ! -f causal_chain2_code.tar.gz ]]; then
  tar czvf causal_chain2_code.tar.gz \
    --exclude='out' \
    --exclude='.git' \
    --exclude='offline_packages' \
    --exclude='README.md.bak' \
    -C /data2/lpy1 causal-chain2
else
  echo "    已存在，跳过"
fi

echo "==> [2/5] conda pack 环境 -> ${SECRET_ENV}（较慢，约数 GB）"
CONDA_PACK="/home/anaconda3/bin/conda-pack"
if [[ ! -x "$CONDA_PACK" ]]; then
  /home/anaconda3/bin/pip install -q conda-pack
fi
if [[ ! -f causal_env_pack.tar.gz ]]; then
  "$CONDA_PACK" --prefix "$ENV_PREFIX" \
    --dest-prefix "$SECRET_ENV" \
    --ignore-missing-files \
    --compress-level 1 \
    -o causal_env_pack.tar.gz -f
else
  echo "    已存在，跳过"
fi

echo "==> [3/5] 打包模型 Qwen2.5-VL.tar.gz（较慢）"
if [[ ! -f Qwen2.5-VL.tar.gz ]]; then
  tar czvf Qwen2.5-VL.tar.gz -C /data2/lpy1 Qwen2.5-VL
else
  echo "    已存在，跳过"
fi

echo "==> [4/5] split 分卷（每卷 ${SPLIT_SIZE}）"
rm -f causal_env_pack.tar.gz.part_* Qwen2.5-VL.tar.gz.part_*
split -b "$SPLIT_SIZE" -d -a 3 causal_env_pack.tar.gz causal_env_pack.tar.gz.part_
split -b "$SPLIT_SIZE" -d -a 3 Qwen2.5-VL.tar.gz Qwen2.5-VL.tar.gz.part_

echo "==> [5/5] 校验文件"
md5sum causal_chain2_code.tar.gz \
  causal_env_pack.tar.gz \
  causal_env_pack.tar.gz.part_* \
  Qwen2.5-VL.tar.gz \
  Qwen2.5-VL.tar.gz.part_* \
  > checksums.md5

ls -lh "$OUT"
echo "Done. 下载 offline_packages/ 下全部文件到本地，再上传涉密机。"
