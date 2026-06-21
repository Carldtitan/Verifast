#!/bin/bash
export HOME=/home/agent
cp "/mnt/c/Users/Mr. Paul/Downloads/Free Chat/rl-fsm/hud-env/train.py" /home/agent/hud-env/train.py
cd /home/agent/hud-env
LOG=/home/agent/hud-env/train_full.log
: > "$LOG"
nohup /home/agent/fsm/.venv/bin/python -u train.py \
  --steps 30 --tasks-per-step 4 --group 8 --lr 1e-5 \
  --eval-every 5 --eval-n 20 --max-concurrent 8 --runtime local \
  >> "$LOG" 2>&1 &
echo "launched PID $!"
echo "log: $LOG"
sleep 3
echo "--- first lines ---"
head -5 "$LOG" 2>/dev/null || echo "(log not yet written)"
