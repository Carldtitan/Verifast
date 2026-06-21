"""Synthetic FSM task generator.

Each task is (English spec prompt, DSL program, golden SystemVerilog). The golden is
produced by the FROZEN transpiler (the trusted oracle), so we never hand the model a
solution — only a spec to satisfy and a hidden golden to grade against.

A task family:
  - random Moore FSM (1-bit guard inputs for guaranteed validity; outputs up to 2 bits)
  - rendered three ways:
      machine.fsm  -> the DSL program (for the DSL action-space arm)
      prompt.txt   -> a plain-English spec (the model's task; same for both arms)
      golden.sv    -> transpiled SystemVerilog from the DSL (the grading oracle)

Usage (run in WSL with the transpiler importable + verilator on PATH):
    python generate.py --out ./generated --n 200 --seed 0
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
from pathlib import Path

# The frozen transpiler lives in the sibling fsm-dsl-transpiler project.
TRANSPILER_ROOT = Path(__file__).resolve().parents[2] / "fsm-dsl-transpiler"
sys.path.insert(0, str(TRANSPILER_ROOT))

from transpiler.parser import parse          # noqa: E402
from transpiler.ast import build_ast          # noqa: E402
from transpiler.safety import check            # noqa: E402
from transpiler.codegen import generate        # noqa: E402

_WORDS = ["idle", "run", "wait", "hold", "load", "scan", "lock", "done", "arm", "fire"]


def _rand_machine(rng: random.Random, cfg: dict) -> dict:
    """Build a random, valid Moore FSM description as a plain dict."""
    n_states = rng.randint(cfg["min_states"], cfg["max_states"])
    states = [f"S{i}" for i in range(n_states)]
    n_in = rng.randint(1, cfg["max_inputs"])
    inputs = [f"i{j}" for j in range(n_in)]          # all 1-bit -> guards always valid
    n_out = rng.randint(1, cfg["max_outputs"])
    outputs = [(f"o{k}", rng.choice([1, 1, 2])) for k in range(n_out)]  # bias to 1-bit
    machine = {
        "name": "fsm_" + "".join(rng.choice(_WORDS) for _ in range(1)),
        "inputs": inputs,
        "outputs": outputs,
        "reset": "S0",
        "states": [],
    }
    for s in states:
        out_vals = {name: rng.randint(0, (1 << w) - 1) for name, w in outputs}
        # guarded transitions then a mandatory else
        whens = []
        for _ in range(rng.randint(0, cfg["max_whens"])):
            cond = rng.choice(inputs)
            tgt = rng.choice(states)
            whens.append((cond, tgt))
        else_tgt = rng.choice(states)
        machine["states"].append({"name": s, "outs": out_vals, "whens": whens, "else": else_tgt})
    return machine


def render_dsl(m: dict) -> str:
    """Render the machine as FSM-DSL source text."""
    lines = [f"machine {m['name']} {{"]
    for i in m["inputs"]:
        lines.append(f"  in bit {i}")
    for name, w in m["outputs"]:
        lines.append(f"  out {'bit' if w == 1 else f'bit[{w-1}:0]'} {name}")
    lines.append(f"  reset = {m['reset']}")
    for st in m["states"]:
        lines.append(f"  state {st['name']} {{")
        for name, _w in m["outputs"]:
            lines.append(f"    {name} = {st['outs'][name]}")
        for cond, tgt in st["whens"]:
            lines.append(f"    when {cond} -> {tgt}")
        lines.append(f"    else -> {st['else']}")
        lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_prompt(m: dict) -> str:
    """Render a plain-English spec the model must implement (same for both arms)."""
    ins = ", ".join(f"{i} (1-bit input)" for i in m["inputs"])
    outs = ", ".join(f"{n} ({w}-bit output)" for n, w in m["outputs"])
    lines = [
        f"Design a synchronous Moore finite state machine named '{m['name']}'.",
        f"Clock 'clk' and synchronous active-high reset 'rst' are implicit inputs.",
        f"Inputs: {ins}.",
        f"Outputs: {outs}.",
        f"On reset the machine is in state {m['reset']}.",
        f"It has {len(m['states'])} states: " + ", ".join(s["name"] for s in m["states"]) + ".",
        "",
        "Per-state behavior (Moore — outputs depend on the current state only):",
    ]
    for st in m["states"]:
        outset = "; ".join(f"{n}={v}" for n, v in st["outs"].items())
        lines.append(f"- In {st['name']}: outputs {outset}.")
        for cond, tgt in st["whens"]:
            lines.append(f"    if {cond} is 1, go to {tgt} (checked in this order);")
        lines.append(f"    otherwise go to {st['else']}.")
    lines.append("")
    lines.append("Write a single synthesizable SystemVerilog module with this exact "
                 "interface. Output only the module.")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./generated")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--min-states", type=int, default=2)
    ap.add_argument("--max-states", type=int, default=5)
    ap.add_argument("--max-inputs", type=int, default=3)
    ap.add_argument("--max-outputs", type=int, default=2)
    ap.add_argument("--max-whens", type=int, default=2)
    args = ap.parse_args()

    cfg = {
        "min_states": args.min_states, "max_states": args.max_states,
        "max_inputs": args.max_inputs, "max_outputs": args.max_outputs,
        "max_whens": args.max_whens,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    made = 0
    attempts = 0
    while made < args.n and attempts < args.n * 5:
        attempts += 1
        m = _rand_machine(rng, cfg)
        dsl = render_dsl(m)
        # Validate + transpile with the FROZEN pipeline (the oracle).
        try:
            program = build_ast(parse(dsl, file="<gen>"), source_file="<gen>")
            diags = check(program)
            if diags:
                continue
            golden = generate(program.machines[0])
        except Exception:
            continue
        task_dir = out / f"task_{made:04d}"
        task_dir.mkdir(exist_ok=True)
        (task_dir / "machine.fsm").write_text(dsl, encoding="utf-8")
        (task_dir / "prompt.txt").write_text(render_prompt(m), encoding="utf-8")
        (task_dir / "golden.sv").write_text(golden, encoding="utf-8")
        made += 1

    print(f"generated {made} tasks into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
