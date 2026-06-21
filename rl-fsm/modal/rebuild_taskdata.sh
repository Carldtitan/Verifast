#!/bin/bash
set -e
ENV=/home/agent/hud-env/task_data
SRC="/mnt/c/Users/Mr. Paul/Downloads/Free Chat/rl-fsm/tasks/generated"

# wipe old flat hard tasks + any prior splits, keep examples
find "$ENV" -maxdepth 1 -type d -name 'task_*' -exec rm -rf {} +
rm -rf "$ENV/train" "$ENV/eval"
mkdir -p "$ENV/train" "$ENV/eval"

copy_split () {
  local src="$1" dst="$2" n="$3" i=0
  for d in "$src"/task_*; do
    [ -d "$d" ] || continue
    [ "$i" -ge "$n" ] && break
    local name; name=$(printf 'task_%04d' "$i")
    mkdir -p "$dst/$name"
    cp "$d/prompt.txt" "$dst/$name/prompt.txt"
    cp "$d/golden.sv"  "$dst/$name/golden.sv"
    i=$((i+1))
  done
  echo "$dst: $i tasks"
}

copy_split "$SRC/train"    "$ENV/train" 60
copy_split "$SRC/held_out" "$ENV/eval"  20

echo "=== layout ==="
echo "train: $(ls -d "$ENV"/train/task_* | wc -l)"
echo "eval:  $(ls -d "$ENV"/eval/task_* | wc -l)"
echo "examples: $(ls "$ENV"/examples 2>/dev/null | wc -l)"
