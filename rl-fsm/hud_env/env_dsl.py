"""HUD environment for the DSL arm — the center of the RL loop.

HUD drives this for BOTH:
  * training rollouts:  hud eval env_dsl.py <model-endpoint> --group 16   (rewards -> advantages)
  * held-out evaluation: hud eval env_dsl.py <model-endpoint> --split held_out_hard

tasks.start  -> DSL prompt (guide + 3 examples + the spec)
tasks.grade  -> extract .fsm, transpile with the FROZEN transpiler, cosim vs golden -> reward

The model is hosted on Modal (vLLM, OpenAI-compatible); HUD calls it and grades here
(verilator + transpiler local to wherever this env runs — WSL with OSS CAD Suite on PATH).
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

from hud import Environment

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hud_env"))
sys.path.insert(0, str(ROOT.parent / "fsm-dsl-transpiler"))

from grader import grade                       # noqa: E402
from transpiler.parser import parse            # noqa: E402
from transpiler.ast import build_ast           # noqa: E402
from transpiler.safety import check            # noqa: E402
from transpiler.codegen import generate        # noqa: E402

env = Environment(name="rl-fsm-dsl-v1")

_REPO = ROOT.parent / "fsm-dsl-transpiler"
_FENCE = re.compile(r"```(?:fsm|dsl)?\s*(.*?)```", re.DOTALL)

_GUIDE_HEAD = """FSM-DSL quick reference:
- machine NAME { ... }            one state machine (clk and rst implicit, never declared)
- in TYPE name / out TYPE name    ports; TYPE is `bit` or `bit[H:L]`
- reset = STATE
- state NAME { ... }              output assignments first, then transitions
- output assignment:  name = INT
- transition:  when COND -> STATE (priority), then a MANDATORY  else -> STATE
- COND over inputs: bare `x`, `x == k`, `x != k`, `x[i]`, combined with && || ! and ( )
Hard rules: assign every output in every state; every state ends with `else -> STATE`.

Examples:
"""


def _guide() -> str:
    ex = "\n\n".join(
        (_REPO / "examples" / f"{n}.fsm").read_text(encoding="utf-8")
        for n in ("seq_detect_101", "traffic_light", "handshake")
    )
    return _GUIDE_HEAD + ex


def _extract(ans: str) -> str:
    m = _FENCE.search(ans or "")
    return (m.group(1) if m else (ans or "")).strip()


def _transpile(fsm_src: str):
    try:
        program = build_ast(parse(fsm_src, file="<gen>"), source_file="<gen>")
        if check(program):
            return None
        return generate(program.machines[0])
    except Exception:
        return None


@env.template(id="fsm_dsl_task")
async def fsm_dsl_task(task_dir: str):
    base = Path(task_dir)
    spec = (base / "prompt.txt").read_text(encoding="utf-8")
    golden = (base / "golden.sv").read_text(encoding="utf-8")
    prompt = (f"{_guide()}\n\n---\nNow write an FSM-DSL program for this specification.\n"
              f"Output ONLY a ```fsm code block.\n\n{spec}")

    answer = yield prompt

    sv = _transpile(_extract(str(answer) if answer is not None else ""))
    if sv is None:
        yield 0.0
        return
    try:
        yield float(grade(sv, golden)["reward"])
    except Exception:
        yield 0.0


def all_tasks(split: str = "train_hard"):
    root = ROOT / "tasks" / "generated" / split
    return [fsm_dsl_task(task_dir=str(d)) for d in sorted(root.glob("task_*")) if d.is_dir()]
