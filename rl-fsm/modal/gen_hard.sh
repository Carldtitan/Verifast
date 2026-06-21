#!/bin/bash
set -e
export HOME=/home/agent
PY=/home/agent/fsm/.venv/bin/python
REPO="/mnt/c/Users/Mr. Paul/Downloads/Free Chat/rl-fsm/tasks"
OUT="$REPO/generated/train_hard2"

# pure-python generation (transpiler oracle, no verilator) -> safe while training runs
cd "$REPO"
"$PY" generate.py --out "$OUT" --n 120 --seed 9001 \
  --min-states 6 --max-states 10 --max-inputs 3 --max-outputs 2 --max-whens 3

echo "generated: $(ls -d "$OUT"/task_* 2>/dev/null | wc -l)"
# stage into env task_data as a separate split (does NOT touch train/)
DST=/home/agent/hud-env/task_data/hardtrain
rm -rf "$DST"; mkdir -p "$DST"
i=0
for d in "$OUT"/task_*; do
  [ -d "$d" ] || continue
  name=$(printf 'task_%04d' "$i")
  mkdir -p "$DST/$name"
  cp "$d/prompt.txt" "$DST/$name/prompt.txt"
  cp "$d/golden.sv"  "$DST/$name/golden.sv"
  i=$((i+1))
done
echo "staged hardtrain: $(ls -d "$DST"/task_* | wc -l)"
