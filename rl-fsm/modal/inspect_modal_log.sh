#!/bin/bash
export HOME=/home/agent
F="/mnt/c/Users/Mr. Paul/Downloads/Free Chat/rl-fsm/modal/live_logs.txt"
echo "=== reward values in live_logs ==="
grep -oE "'reward': [0-9.]+" "$F" | head -40
echo "=== step markers ==="
grep -oE "[0-9]+/200" "$F" | head -40
echo "=== hud models help ==="
/home/agent/fsm/.venv/bin/hud models --help 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | tail -14
