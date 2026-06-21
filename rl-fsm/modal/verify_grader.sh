#!/bin/bash
export HOME=/home/agent
PY=/home/agent/fsm/.venv/bin/python
SRC="/mnt/c/Users/Mr. Paul/Downloads/Free Chat/rl-fsm/hud-env"
DST=/home/agent/hud-env
cp "$SRC/grader.py" "$DST/grader.py"
cp "$SRC/env.py" "$DST/env.py"
echo "synced grader.py + env.py"
cd "$DST"
"$PY" - <<'PY'
import sys; sys.path.insert(0,".")
from pathlib import Path
from grader import grade
g = Path("task_data/train/task_0000/golden.sv").read_text()
print("golden vs golden:", grade(g, g)["reward"], "(expect 1.0)")
# broken: flip an output by truncating logic -> wrong behavior
broken = g.replace("S0", "S0").replace("o0 = 1", "o0 = 0") if "o0 = 1" in g else g + "\n"
print("self-mutated grade:", grade(broken, g)["reward"], "(expect < 1.0 if mutation took)")
PY
