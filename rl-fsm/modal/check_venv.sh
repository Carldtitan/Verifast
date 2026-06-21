#!/bin/bash
export HOME=/home/agent
PY=/home/agent/fsm/.venv/bin/python
"$PY" - <<'PY'
import importlib, sys
for m in ["hud", "lark", "openai", "torch"]:
    try:
        mod = importlib.import_module(m)
        print(f"OK   {m} {getattr(mod,'__version__','?')}")
    except Exception as e:
        print(f"MISS {m}: {e.__class__.__name__}")
# can we import the agent + training surfaces?
for path in ["hud.agents:create_agent", "hud.train:TrainingClient", "hud.eval:Taskset", "hud.eval:Job", "hud.eval:HUDRuntime"]:
    mod, attr = path.split(":")
    try:
        m = importlib.import_module(mod); getattr(m, attr)
        print(f"OK   {path}")
    except Exception as e:
        print(f"MISS {path}: {e}")
PY
