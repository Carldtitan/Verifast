#!/bin/bash
set -e
export HOME=/home/agent
PY=/home/agent/fsm/.venv/bin/python
SRC="/mnt/c/Users/Mr. Paul/Downloads/Free Chat/rl-fsm"
DST=/home/agent/hud-env

cp "$SRC/hud-env/eval_local.py" "$DST/eval_local.py"

# add a 'hard' split into the env task_data from held_out_hard
mkdir -p "$DST/task_data/hard"
i=0
for d in "$SRC/tasks/generated/held_out_hard"/task_*; do
  [ -d "$d" ] || continue
  name=$(printf 'task_%04d' "$i")
  mkdir -p "$DST/task_data/hard/$name"
  cp "$d/prompt.txt" "$DST/task_data/hard/$name/prompt.txt"
  cp "$d/golden.sv"  "$DST/task_data/hard/$name/golden.sv"
  i=$((i+1))
done
echo "hard split: $(ls -d "$DST"/task_data/hard/task_* | wc -l) tasks"

cd "$DST"
echo "================ BASELINE: held-out (easy) ================"
"$PY" eval_local.py --split eval --mode dsl --n 20 --model fsm-rl --max-concurrent 6
echo "================ BASELINE: hard ================"
"$PY" eval_local.py --split hard --mode dsl --n 20 --model fsm-rl --max-concurrent 6
