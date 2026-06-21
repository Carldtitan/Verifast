#!/bin/bash
export HOME=/home/agent
echo "############## MODAL: apps (rl-fsm-train*) ##############"
/home/agent/fsm/.venv/bin/python -m modal app list 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | grep -Ei 'app id|rl-fsm|train|state|ephemeral|stopped' | head -30 || python3 -m modal app list 2>/dev/null | head
echo
echo "############## MODAL: volume rl-fsm-weights contents ##############"
/home/agent/fsm/.venv/bin/python -m modal volume ls rl-fsm-weights 2>/dev/null | head -20
echo "--- dsl_latest ---"
/home/agent/fsm/.venv/bin/python -m modal volume ls rl-fsm-weights dsl_latest 2>/dev/null | head -40
