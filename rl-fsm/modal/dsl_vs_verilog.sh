#!/bin/bash
export HOME=/home/agent
PY=/home/agent/fsm/.venv/bin/python
"$PY" -c "import matplotlib; print('matplotlib', matplotlib.__version__)"
cd /home/agent/hud-env
echo "############ BASE Qwen3-8B  -- VERILOG arm (held-out, greedy) ############"
"$PY" eval_local.py --split eval --mode verilog --n 20 --model Qwen/Qwen3-8B --max-concurrent 6 2>&1 | grep -E 'model=|mean_reward|pass@1|behavior'
echo "############ TRAINED fsm-rl -- VERILOG arm (held-out, greedy) ############"
"$PY" eval_local.py --split eval --mode verilog --n 20 --model fsm-rl --max-concurrent 6 2>&1 | grep -E 'model=|mean_reward|pass@1|behavior'
