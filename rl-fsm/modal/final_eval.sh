#!/bin/bash
export HOME=/home/agent
PY=/home/agent/fsm/.venv/bin/python
SRC="/mnt/c/Users/Mr. Paul/Downloads/Free Chat/rl-fsm/hud-env"
cp "$SRC/eval_local.py" /home/agent/hud-env/eval_local.py
cd /home/agent/hud-env
echo "################ BASE: Qwen/Qwen3-8B (held-out, greedy) ################"
"$PY" eval_local.py --split eval --mode dsl --n 20 --model Qwen/Qwen3-8B --max-concurrent 6 2>&1 | grep -E 'model=|mean_reward|pass@1|behavior|histogram'
echo "################ TRAINED: fsm-rl (held-out, greedy) ################"
"$PY" eval_local.py --split eval --mode dsl --n 20 --model fsm-rl --max-concurrent 6 2>&1 | grep -E 'model=|mean_reward|pass@1|behavior|histogram'
