#!/bin/bash
export HOME=/home/agent
PY=/home/agent/fsm/.venv/bin/python
echo "=== matplotlib in WSL venv? ==="
"$PY" -c "import matplotlib; print('matplotlib', matplotlib.__version__)" 2>&1 | head -1
echo
echo "=== Modal training log snippet (live_logs.txt) ==="
ls -la "/mnt/c/Users/Mr. Paul/Downloads/Free Chat/rl-fsm/modal/live_logs.txt" 2>&1 | head -1
grep -cE "'reward':" "/mnt/c/Users/Mr. Paul/Downloads/Free Chat/rl-fsm/modal/live_logs.txt" 2>/dev/null || echo "no reward lines"
echo
echo "=== hud models subcommands (export/download?) ==="
"$BIN/hud" models --help 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -iE 'download|export|pull|weights|checkpoint' || /home/agent/fsm/.venv/bin/hud models --help 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | tail -15
