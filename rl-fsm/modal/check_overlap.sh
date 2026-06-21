#!/bin/bash
D=/home/agent/hud-env/task_data
# hash each prompt; compare train vs eval for any identical spec (leakage check)
train_hashes=$(for f in "$D"/train/task_*/prompt.txt; do md5sum "$f" | awk '{print $1}'; done | sort -u)
eval_hashes=$(for f in "$D"/eval/task_*/prompt.txt; do md5sum "$f" | awk '{print $1}'; done | sort -u)
echo "train unique specs: $(echo "$train_hashes" | wc -l)"
echo "eval unique specs:  $(echo "$eval_hashes" | wc -l)"
overlap=$(comm -12 <(echo "$train_hashes") <(echo "$eval_hashes") | wc -l)
echo "OVERLAP (train ∩ eval): $overlap  (0 = clean held-out)"
