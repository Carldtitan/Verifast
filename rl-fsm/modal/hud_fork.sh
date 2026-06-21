#!/bin/bash
export HOME=/home/agent
BIN=/home/agent/fsm/.venv/bin
echo "=== existing trainable forks (mine) ==="
"$BIN/hud" models checkpoints fsm-rl 2>&1 | head -10 || true
echo "=== forking Qwen3-8B -> fsm-rl ==="
"$BIN/hud" models fork Qwen/Qwen3-8B --name fsm-rl 2>&1 | head -30
