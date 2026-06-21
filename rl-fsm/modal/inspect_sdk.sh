#!/bin/bash
P=/home/agent/fsm/.venv/lib/python3.12/site-packages/hud/eval
echo "===== TASKSET (run sig) ====="
grep -n 'def run\|async def run\|def __init__\|^class \|group' "$P/taskset.py" | head -40
echo "===== JOB ====="
grep -n 'def start\|async def start\|def __init__\|^class \|runs' "$P/job.py" | head -40
echo "===== RUNTIME classes ====="
grep -n '^class \|def __init__' "$P/runtime.py" | head -50
