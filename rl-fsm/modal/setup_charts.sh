#!/bin/bash
export HOME=/home/agent
/home/agent/fsm/.venv/bin/python -m pip install -q matplotlib 2>&1 | tail -3
/home/agent/fsm/.venv/bin/python -c "import matplotlib; print('matplotlib ok', matplotlib.__version__)"
