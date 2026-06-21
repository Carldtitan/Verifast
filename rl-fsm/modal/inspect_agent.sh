#!/bin/bash
SP=/home/agent/fsm/.venv/lib/python3.12/site-packages
echo "===== create_agent signature ====="
grep -n 'def create_agent' "$SP/hud/agents/__init__.py" 2>/dev/null || grep -rn 'def create_agent' "$SP/hud/agents/" | head
echo "----- body (first match file) -----"
f=$(grep -rl 'def create_agent' "$SP/hud/agents/" | head -1); echo "file: $f"; awk '/def create_agent/{p=1} p{print} p&&/return /{c++; if(c>0 && /:/) }' "$f" | head -40
echo "===== TrainingClient.step ====="
grep -n 'def step' "$SP/hud/train/client.py"
awk '/async def step/{p=1} p{print NR": "$0} p&&/->/{if(++c>=1)exit}' "$SP/hud/train/client.py" | head -40
