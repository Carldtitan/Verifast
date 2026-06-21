#!/bin/bash
set -e
SRC="/mnt/c/Users/Mr. Paul/Downloads/Free Chat/rl-fsm/hud-env"
DST="/home/agent/hud-env"
for f in env.py tasks.py grader.py train.py pyproject.toml; do
  cp "$SRC/$f" "$DST/$f"
  echo "copied $f"
done
echo "=== task_data layout in DST ==="
echo "train: $(ls -d "$DST"/task_data/train/task_* 2>/dev/null | wc -l)"
echo "eval:  $(ls -d "$DST"/task_data/eval/task_* 2>/dev/null | wc -l)"
echo "examples: $(ls "$DST"/task_data/examples/*.fsm 2>/dev/null | wc -l)"
echo "stray flat task_ dirs: $(ls -d "$DST"/task_data/task_* 2>/dev/null | wc -l)"
