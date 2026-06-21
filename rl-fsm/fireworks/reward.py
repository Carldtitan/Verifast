"""Fireworks reward-kit evaluator: our DSL transpile+cosim grader as an RFT reward.

The model's completion is FSM-DSL. We extract it, transpile with the frozen transpiler,
cosim the generated SystemVerilog against the task golden, and return the reward (0..1).

ground_truth carries the task's golden SystemVerilog.
Requires verilator on PATH wherever this runs (locally: WSL + OSS CAD Suite).
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hud_env"))
sys.path.insert(0, str(ROOT.parent / "fsm-dsl-transpiler"))

from reward_kit import reward_function, EvaluateResult  # noqa: E402
from grader import grade                                  # noqa: E402
from transpiler.parser import parse                       # noqa: E402
from transpiler.ast import build_ast                      # noqa: E402
from transpiler.safety import check                       # noqa: E402
from transpiler.codegen import generate as gen_sv         # noqa: E402

_FENCE = re.compile(r"```(?:fsm|dsl)?\s*(.*?)```", re.DOTALL)


def _extract(text: str) -> str:
    m = _FENCE.search(text or "")
    return (m.group(1) if m else (text or "")).strip()


def _transpile(src: str):
    try:
        p = build_ast(parse(src, file="<g>"), source_file="<g>")
        return None if check(p) else gen_sv(p.machines[0])
    except Exception:
        return None


def _completion_text(messages) -> str:
    if not messages:
        return ""
    last = messages[-1]
    return last.get("content", "") if isinstance(last, dict) else getattr(last, "content", "")


@reward_function
def evaluate(messages, ground_truth=None, **kwargs) -> EvaluateResult:
    """Score one DSL completion against the task golden (ground_truth)."""
    completion = _completion_text(messages)
    sv = _transpile(_extract(completion))
    if sv is None:
        return EvaluateResult(score=0.0, reason="invalid/unsafe DSL -> transpiler rejected")
    if not ground_truth:
        return EvaluateResult(score=0.0, reason="no golden provided")
    try:
        r = grade(sv, ground_truth)
        return EvaluateResult(score=float(r["reward"]),
                              reason=f"reward={r['reward']} parts={r['parts']}")
    except Exception as e:  # noqa: BLE001
        return EvaluateResult(score=0.0, reason=f"grading error: {e}")
