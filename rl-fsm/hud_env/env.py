"""HUD FSM environment.

tasks.start  -> the English FSM spec (prompt)
tasks.grade  -> cosim the model's SystemVerilog against the task golden -> reward 0..1

One template spans the whole dataset: each task directory (prompt.txt + golden.sv,
produced by tasks/generate.py) becomes a runnable HUD Task. Run with:

    hud eval env.py <model> --group 16          # rollouts (training data / advantages)
    hud eval env.py <model> --task-ids held_*    # held-out evaluation

The reward is the calibrated cosim grader (golden=1.0, broken<1.0).
"""

from __future__ import annotations

import re
from pathlib import Path

from hud import Environment

from grader import grade

env = Environment(name="rl-fsm-v1")

TASKS_ROOT = Path(__file__).resolve().parent.parent / "tasks" / "generated"

_FENCE = re.compile(r"```(?:systemverilog|verilog|sv)?\s*(.*?)```", re.DOTALL)


def _extract_sv(answer: str) -> str:
    """Pull the SystemVerilog out of a model answer (strip markdown fences if present)."""
    if answer is None:
        return ""
    m = _FENCE.search(answer)
    return (m.group(1) if m else answer).strip()


@env.template(id="fsm_task")
async def fsm_task(task_dir: str):
    """Run one FSM spec->RTL task: yield the prompt, grade the SV answer by cosim."""
    base = Path(task_dir)
    prompt = (base / "prompt.txt").read_text(encoding="utf-8")
    golden = (base / "golden.sv").read_text(encoding="utf-8")

    answer = yield prompt

    candidate = _extract_sv(str(answer) if answer is not None else "")
    if not candidate:
        yield 0.0
        return
    try:
        result = grade(candidate, golden)
        yield float(result["reward"])
    except Exception:
        # Fail closed: an ungradeable answer scores 0, never errors the rollout.
        yield 0.0


def all_tasks(split: str = "train"):
    """Mint one Task per generated task directory under tasks/generated/<split>."""
    root = TASKS_ROOT / split
    return [fsm_task(task_dir=str(d)) for d in sorted(root.glob("task_*")) if d.is_dir()]
