#!/bin/bash
export HOME=/home/agent
BIN=/home/agent/fsm/.venv/bin
echo "############## HUD: trained model checkpoint tree ##############"
"$BIN/hud" models checkpoints fsm-rl 2>&1 | head -60
echo
echo "############## HUD: jobs (recent) ##############"
"$BIN/hud" jobs 2>&1 | head -40
