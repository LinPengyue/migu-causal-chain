#!/usr/bin/env bash
cd /data2/lpy1/worktrees/migu-sportscausal-template-gen/research/sportscausal
python run_fresh_v3r_general.py \
  --match-json "/data2/lpy1/worktrees/migu-sportscausal-template-gen/data/交付_out/10月20日_25-26赛季西甲第9轮_莱万特VS巴列卡诺_国语.json" \
  --causal-atoms-json "/data2/lpy1/worktrees/migu-sportscausal-template-gen/data/交付_out/10月20日_25-26赛季西甲第9轮_莱万特VS巴列卡诺_国语_causal.json" --allow-dev \
  --source-mp4 "/mnt/data4/migu/10月20日 25-26赛季西甲第9轮 莱万特VS巴列卡诺 国语.mp4" \
  --expected-source-sha256 5ab8ee77ed0d0cb56f020348d4c73b4c27c738f6285db941e1797f87bb1d4d73 \
  --expected-events-sha256 cffe1f86aa386e668b6ad3ce8a654113a814783b9343db4ce63bb6ebb5f2e9c6 \
  --expected-atom-source-sha256 e88ce072fcd22c2a723abd3374b9c29f6ef5584fe8ac0bd6431e4c84decfdbd1 \
  --score-left-team team_1 \
  --score-mapping-provenance "independently_cross_checked_intake_FH-35DA83FD: left scoreboard column = team_1 莱万特, right = team_2 巴列卡诺; matches T01 score_path 0:0→0:1→0:2→0:3 with delta_side=right for Rayo goals" \
  --video-id "10月20日 25-26赛季西甲第9轮 莱万特VS巴列卡诺 国语" \
  --out-dir "/data2/lpy1/worktrees/migu-sportscausal-template-gen/research/sportscausal/artifacts/v3r_general_C_levante_rayo/fresh_general_v1"
