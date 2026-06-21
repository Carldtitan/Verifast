#!/bin/bash
export HOME=/home/agent
export HUD_API_KEY=$(grep HUD_API_KEY /home/agent/.hud/.env | tr -d '\r' | sed 's/.*=//;s/"//g')
DEMO="/mnt/c/Users/Mr. Paul/Downloads/Free Chat/rl-fsm/demo"
cd "$DEMO"
/home/agent/fsm/.venv/bin/python compare.py --task task_0000 --temperature 0.0
