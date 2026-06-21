#!/bin/bash
export HOME=/home/agent
cp "/mnt/c/Users/Mr. Paul/Downloads/Free Chat/rl-fsm/hud-env/train.py" /home/agent/hud-env/train.py
/home/agent/fsm/.venv/bin/python -c "import ast; ast.parse(open('/home/agent/hud-env/train.py').read()); print('syntax ok')"
cd /home/agent/hud-env
echo "=== 1-step validation (eval wiring) ==="
/home/agent/fsm/.venv/bin/python train.py --steps 1 --tasks-per-step 2 --group 4 --eval-every 1 --eval-n 4 --max-concurrent 6 --runtime local 2>&1 | grep -E "EVAL|step |TRAIN_DONE|Error|Traceback"
