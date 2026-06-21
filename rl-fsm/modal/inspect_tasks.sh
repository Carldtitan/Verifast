#!/bin/bash
R="/mnt/c/Users/Mr. Paul/Downloads/Free Chat/rl-fsm/tasks/generated"
echo "=== one train task files ==="
ls "$R/train/task_0000"
echo "--- prompt head ---"
head -8 "$R/train/task_0000/prompt.txt"
echo "--- golden head ---"
head -6 "$R/train/task_0000/golden.sv"
echo
echo "train count:    $(ls -d "$R"/train/task_* 2>/dev/null | wc -l)"
echo "held_out count: $(ls -d "$R"/held_out/task_* 2>/dev/null | wc -l)"
echo "held_out_hard:  $(ls -d "$R"/held_out_hard/task_* 2>/dev/null | wc -l)"
