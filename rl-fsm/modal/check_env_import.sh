#!/bin/bash
export HOME=/home/agent
PY=/home/agent/fsm/.venv/bin/python
cd /home/agent/hud-env
"$PY" - <<'PY'
import sys
sys.path.insert(0, ".")
import tasks
print("env name:", tasks.env.name)
print("eval tasks:", len(tasks.tasks))
print("sample slug:", tasks.tasks[0].slug, "| cols:", tasks.tasks[0].columns)
# train pool
import train
print("train pool size:", len(train._pool()))
print("OK imports")
PY
