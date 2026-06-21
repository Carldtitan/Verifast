"""Side-by-side terminal comparison: fine-tuned DSL vs base Verilog on the SAME spec.

    export HUD_API_KEY=sk-hud-...
    python compare.py                 # random task
    python compare.py --task task_0003
    python compare.py --dsl-model fsm-rl --verilog-model Qwen/Qwen3-8B

Prints each arm's generated code, the verifier score breakdown, tokens, latency, speed.
"""
from __future__ import annotations

import argparse
import random
import textwrap

import core


def _box(title: str, body: str, width: int = 78) -> str:
    line = "=" * width
    return f"{line}\n{title}\n{line}\n{body}\n"


def _fmt(res: core.ArmResult) -> str:
    p = res.parts or {}
    verdict = "PASS ✅" if res.passed else "FAIL ❌"
    lines = [
        f"model            : {res.model}",
        f"verdict          : {verdict}   reward={res.reward:.3f}",
        f"  compiles       : {p.get('compile', 0):.0f}   (weight 0.2)",
        f"  lint-clean     : {p.get('lint', 0):.0f}   (weight 0.1)",
        f"  behaviour match: {p.get('behavior', 0):.0f}   (weight 0.7)",
        f"prompt tokens    : {res.prompt_tokens}",
        f"completion tokens: {res.completion_tokens}",
        f"latency          : {res.latency_s:.2f} s",
        f"speed            : {res.tokens_per_s:.1f} tok/s",
        "",
        "----- raw model output -----",
        (res.raw_output or "(empty)"),
        "",
        "----- SystemVerilog (verified) -----",
        (res.code or "(no parseable code produced)"),
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default=None)
    ap.add_argument("--dsl-model", default=core.DSL_MODEL_DEFAULT)
    ap.add_argument("--verilog-model", default=core.VERILOG_MODEL_DEFAULT)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--temperature", type=float, default=0.0)
    args = ap.parse_args()

    cli = core.client(args.api_key)
    tasks = core.list_tasks()
    name = args.task or random.choice(tasks)
    spec, golden = core.load_task(name)

    print(_box(f"TASK: {name}  (identical spec sent to both models)", spec.strip()))

    print("Running fine-tuned model on the DSL arm ...")
    dsl = core.run_arm(cli, "DSL", args.dsl_model, spec, golden, temperature=args.temperature)
    print("Running base model on the Verilog arm ...\n")
    ver = core.run_arm(cli, "Verilog", args.verilog_model, spec, golden, temperature=args.temperature)

    print(_box(f"ARM 1 — FINE-TUNED  ({args.dsl_model})  •  writes FSM-DSL", _fmt(dsl)))
    print(_box(f"ARM 2 — BASE        ({args.verilog_model})  •  writes raw Verilog", _fmt(ver)))

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"  DSL  (fine-tuned): reward {dsl.reward:.3f}  {'PASS' if dsl.passed else 'FAIL'}"
          f"  | {dsl.completion_tokens} tok  {dsl.latency_s:.2f}s  {dsl.tokens_per_s:.1f} tok/s")
    print(f"  Verilog (base)   : reward {ver.reward:.3f}  {'PASS' if ver.passed else 'FAIL'}"
          f"  | {ver.completion_tokens} tok  {ver.latency_s:.2f}s  {ver.tokens_per_s:.1f} tok/s")


if __name__ == "__main__":
    main()
