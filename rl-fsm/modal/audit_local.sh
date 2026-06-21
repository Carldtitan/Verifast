#!/bin/bash
R="/mnt/c/Users/Mr. Paul/Downloads/Free Chat/rl-fsm"
echo "############## RUN 1 log (held-out eval line) ##############"
grep -E 'EVAL' "$R/hud-env/train_full.log" 2>/dev/null
echo
echo "############## RUN 2 log (held-out eval lines) ##############"
grep -E 'EVAL' "$R/hud-env/train_run2.log" 2>/dev/null
echo
echo "############## baseline runs dir (Modal/Qwen/Claude experiments) ##############"
ls "$R/runs" 2>/dev/null
echo
echo "############## results.json files ##############"
find "$R/runs" -name 'results.json' 2>/dev/null | while read f; do echo "--- $f ---"; head -c 600 "$f"; echo; done
echo
echo "############## hud-env logs present ##############"
ls -la "$R/hud-env/"*.log 2>/dev/null
