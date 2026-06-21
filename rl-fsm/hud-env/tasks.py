"""Eval taskset for the FSM-DSL HUD environment (the held-out leaderboard).

Held-out FSM specs the model never trains on. Two tasks per spec — the DSL arm and
the Verilog arm — so the HUD leaderboard shows the head-to-head and the base-vs-trained
lift. `env` is re-exported because `hud eval tasks.py` serves THIS module.

    hud eval tasks.py <model> --remote
    hud eval tasks.py <model> --remote --task-ids task_0000-dsl   # one arm
"""
from pathlib import Path

from env import env, fsm_task  # noqa: F401  (env re-exported for `hud eval tasks.py`)

EVAL_DIR = Path(__file__).resolve().parent / "task_data" / "eval"

tasks = []
for _d in sorted(EVAL_DIR.glob("task_*")):
    if not _d.is_dir():
        continue
    for _mode in ("dsl", "verilog"):
        _t = fsm_task(task_dir=f"eval/{_d.name}", mode=_mode)
        _t.slug = f"{_d.name}-{_mode}"
        _t.columns = {"task": _d.name, "mode": _mode, "split": "held_out", "domain": "fsm-hardware"}
        tasks.append(_t)
