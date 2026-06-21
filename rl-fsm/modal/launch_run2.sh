#!/bin/bash
export HOME=/home/agent
cp "/mnt/c/Users/Mr. Paul/Downloads/Free Chat/rl-fsm/hud-env/train.py" /home/agent/hud-env/train.py
/home/agent/fsm/.venv/bin/python -c "import ast; ast.parse(open('/home/agent/hud-env/train.py').read()); print('syntax ok')"
cd /home/agent/hud-env
LOG=/home/agent/hud-env/train_run2.log
: > "$LOG"
nohup /home/agent/fsm/.venv/bin/python -u train.py \
  --train-split hardtrain --steps 40 --tasks-per-step 4 --group 8 --lr 2e-5 \
  --temp 1.1 --eval-temp 0.0 --eval-every 5 --eval-n 20 \
  --max-concurrent 8 --runtime local \
  >> "$LOG" 2>&1 &
echo "launched run2 PID $!"
sleep 3
head -4 "$LOG" 2>/dev/null || echo "(no log yet)"
