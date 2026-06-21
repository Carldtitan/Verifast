#!/bin/bash
P=/home/agent/fsm/.venv/lib/python3.12/site-packages/hud/eval
echo "########## Taskset.__init__ + run ##########"
sed -n '48,90p;211,245p' "$P/taskset.py"
echo "########## Job.start ##########"
sed -n '34,80p' "$P/job.py"
echo "########## HUDRuntime ##########"
sed -n '712,760p' "$P/runtime.py"
echo "########## HostedRuntime ##########"
sed -n '838,900p' "$P/runtime.py"
