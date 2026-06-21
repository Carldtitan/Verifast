#!/bin/bash
export HOME=/home/agent
PY=/home/agent/fsm/.venv/bin/python
cd /home/agent/hud-env
echo "verilator on PATH:"; which verilator; verilator --version 2>&1 | head -1
echo "=== golden vs golden (expect reward 1.0) ==="
"$PY" - <<'PY'
import sys; sys.path.insert(0,".")
from pathlib import Path
from grader import grade
g = Path("task_data/train/task_0000/golden.sv").read_text()
print(grade(g, g))
PY
