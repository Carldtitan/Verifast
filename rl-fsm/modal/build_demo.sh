#!/bin/bash
set -e
DEMO="/mnt/c/Users/Mr. Paul/Downloads/Free Chat/rl-fsm/demo"
HUDENV=/home/agent/hud-env

# transpiler + grader (from the deployed env, which is the frozen/working copy)
rm -rf "$DEMO/transpiler"; cp -r "$HUDENV/transpiler" "$DEMO/transpiler"
cp "$HUDENV/grader.py" "$DEMO/grader.py"

# sample tasks: 6 held-out specs + the DSL examples used in the guide
mkdir -p "$DEMO/tasks/examples"
cp "$HUDENV/task_data/examples/"*.fsm "$DEMO/tasks/examples/"
i=0
for d in "$HUDENV"/task_data/eval/task_*; do
  [ -d "$d" ] || continue
  [ "$i" -ge 6 ] && break
  name=$(basename "$d")
  mkdir -p "$DEMO/tasks/$name"
  cp "$d/prompt.txt" "$DEMO/tasks/$name/prompt.txt"
  cp "$d/golden.sv"  "$DEMO/tasks/$name/golden.sv"
  i=$((i+1))
done
echo "demo tasks: $(ls -d "$DEMO"/tasks/task_* | wc -l)"
echo "examples:   $(ls "$DEMO"/tasks/examples/*.fsm | wc -l)"
echo "transpiler: $(ls "$DEMO"/transpiler/*.py | wc -l) py files"
echo "--- demo tree ---"
ls "$DEMO"
