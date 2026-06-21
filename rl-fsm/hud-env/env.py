"""HUD RL environment: FSM hardware design.

The agent gets a natural-language FSM spec and writes hardware in one of two action spaces:
  * mode="dsl"     -> writes the LLM-friendly FSM-DSL; we transpile it to SystemVerilog
  * mode="verilog" -> writes raw SystemVerilog directly
Either way the reward is transpile(if dsl) -> Verilator cosim against the hidden golden.

Single-turn: tasks.start yields the prompt, tasks.grade returns reward 0..1. Verilator must
be on PATH in the env image (installed via apt in Dockerfile.hud). This is the deployable
HUD environment that demonstrates DSL-vs-Verilog and is used for eval + the leaderboard.

    hud deploy .
    hud eval tasks.py <model> --remote          # all tasks (both arms)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from hud import Environment

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from grader import grade                          # noqa: E402
from transpiler.parser import parse               # noqa: E402
from transpiler.ast import build_ast              # noqa: E402
from transpiler.safety import check               # noqa: E402
from transpiler.codegen import generate as gen_sv  # noqa: E402

env = Environment(name="fsm-dsl-rl-v1")

TASK_DATA = ROOT / "task_data"
_FENCE_FSM = re.compile(r"```(?:fsm|dsl)?\s*(.*?)```", re.DOTALL)
_FENCE_SV = re.compile(r"```(?:systemverilog|verilog|sv)?\s*(.*?)```", re.DOTALL)

_GUIDE_HEAD = (
    "FSM-DSL quick reference:\n"
    "- machine NAME { ... }  (clk/rst implicit, never declared)\n"
    "- in TYPE name / out TYPE name  (TYPE = bit or bit[H:L])\n"
    "- reset = STATE\n"
    "- state NAME { output assignments first, then transitions }\n"
    "- output assignment:  name = INT\n"
    "- transition:  when COND -> STATE (priority), then a MANDATORY  else -> STATE\n"
    "- COND over inputs: bare x, x==k, x!=k, x[i], with && || ! ( )\n"
    "Rules: assign every output in every state; every state ends with else -> STATE.\n\nExamples:\n"
)


def _dsl_guide() -> str:
    ex = "\n\n".join(
        (TASK_DATA / "examples" / f"{n}.fsm").read_text(encoding="utf-8")
        for n in ("seq_detect_101", "traffic_light", "handshake")
    )
    return _GUIDE_HEAD + ex


def _transpile(src: str):
    try:
        p = build_ast(parse(src, file="<g>"), source_file="<g>")
        return None if check(p) else gen_sv(p.machines[0])
    except Exception:
        return None


@env.template(id="fsm_task")
async def fsm_task(task_dir: str, mode: str = "dsl"):
    base = TASK_DATA / task_dir
    spec = (base / "prompt.txt").read_text(encoding="utf-8")
    golden = (base / "golden.sv").read_text(encoding="utf-8")

    if mode == "dsl":
        prompt = (f"{_dsl_guide()}\n\n---\nNow write an FSM-DSL program for this "
                  f"specification. Output ONLY a ```fsm code block.\n\n{spec}\n\n/no_think")
    else:
        prompt = ("You are an expert hardware engineer. Write only synthesizable "
                  "SystemVerilog inside a ```systemverilog code block.\n\n" + spec
                  + "\n\n/no_think")

    answer = yield prompt

    text = str(answer) if answer is not None else ""
    if mode == "dsl":
        m = _FENCE_FSM.search(text)
        sv = _transpile((m.group(1) if m else text).strip())
    else:
        m = _FENCE_SV.search(text)
        sv = (m.group(1) if m else text).strip() or None

    if not sv:
        yield 0.0
        return
    try:
        yield float(grade(sv, golden)["reward"])
    except Exception:
        yield 0.0
