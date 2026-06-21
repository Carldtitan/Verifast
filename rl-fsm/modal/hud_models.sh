#!/bin/bash
export HOME=/home/agent
BIN=/home/agent/fsm/.venv/bin
"$BIN/hud" models list --json 2>/dev/null > /tmp/models.json
python3 - <<'PY'
import json
m = json.load(open("/tmp/models.json"))
print("total models:", len(m))
print("\n=== TRAINABLE ===")
for x in m:
    if x.get("trainable") or x.get("is_trainable"):
        print(x.get("name"), "|", x.get("model_name"), "|", x.get("provider"), "|", x.get("id"))
print("\n=== any QWEN ===")
for x in m:
    s=json.dumps(x).lower()
    if "qwen" in s:
        print(x.get("name"), "|", x.get("model_name"), "|", x.get("provider"), "| trainable=", x.get("trainable") or x.get("is_trainable"))
PY
