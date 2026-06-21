"""Non-FSM benchmark: base Qwen vs fine-tuned model on verilog-template RTL repair.

Verifast DSL is FSM-only — it cannot express a FIFO arbiter. This script compares:
  * Fine-tuned model (fsm-rl) fixing buggy SystemVerilog
  * Base model (Qwen/Qwen3-8B) fixing the same buggy RTL

Graded by the verilog-template repair grader (functional sim + synthesis + lint).

    export HUD_API_KEY=sk-hud-...
    python compare_non_fsm.py
    python compare_non_fsm.py --task stream_arb_fifo_repair
    python compare_non_fsm.py --task task_mux4
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parent
VERILOG_ROOT = ROOT.parents[1] / "verilog-template"
sys.path.insert(0, str(ROOT))

from core import (  # noqa: E402
    DSL_MODEL_DEFAULT,
    GATEWAY_URL,
    VERILOG_MODEL_DEFAULT,
    client,
    dsl_prompt,
    transpile,
    verilog_prompt,
)
from grader import grade as cosim_grade  # noqa: E402

_FENCE_SV = re.compile(r"```(?:systemverilog|verilog|sv)?\s*(.*?)```", re.DOTALL)
_FENCE_FSM = re.compile(r"```(?:fsm|dsl)?\s*(.*?)```", re.DOTALL)

NON_FSM_TASKS = {
    "stream_arb_fifo_repair": {
        "kind": "repair",
        "rtl": VERILOG_ROOT / "tasks/stream_arb_fifo_repair/rtl/stream_arb_fifo.sv",
        "prompt": VERILOG_ROOT / "tasks/stream_arb_fifo_repair/prompt.md",
        "grader": VERILOG_ROOT / "tasks/stream_arb_fifo_repair/donotaccess/grade.py",
        "hidden": VERILOG_ROOT / "tasks/stream_arb_fifo_repair/donotaccess",
        "module": "stream_arb_fifo",
    },
    "task_mux4": {
        "kind": "design",
        "prompt": ROOT / "tasks/task_mux4/prompt.txt",
        "golden": ROOT / "tasks/task_mux4/golden.sv",
        "module": "mux4",
    },
}


def _load_grader(path: Path):
    spec = importlib.util.spec_from_file_location("repair_grade", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load grader at {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def repair_prompt(spec_text: str, buggy_rtl: str) -> str:
    return (
        "You are an expert hardware engineer. The following SystemVerilog module has bugs. "
        "Return the COMPLETE fixed module in a single ```systemverilog code block. "
        "Keep the module name and port list unchanged.\n\n"
        f"Specification:\n{spec_text.strip()}\n\n"
        f"Buggy RTL (fix this):\n```systemverilog\n{buggy_rtl.strip()}\n```\n\n/no_think"
    )


def dsl_design_prompt(spec_text: str) -> str:
    return dsl_prompt(
        f"{spec_text.strip()}\n\n"
        "Note: this is NOT an FSM — combinational logic. "
        "FSM-DSL cannot express it; output will fail transpile."
    )


def dsl_repair_prompt(spec_text: str, buggy_rtl: str) -> str:
    return (
        dsl_prompt(
            f"Specification:\n{spec_text.strip()}\n\n"
            "Note: this is NOT an FSM task — a FIFO arbiter. "
            "Write the best FSM-DSL you can, or explain if impossible."
        )
        + "\n\nBuggy reference RTL for context:\n```systemverilog\n"
        + buggy_rtl.strip()
        + "\n```"
    )


@dataclass
class NonFsmResult:
    arm: str
    model: str
    raw_output: str = ""
    code: str | None = None
    reward: float = 0.0
    parts: dict = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    note: str = ""

    @property
    def tokens_per_s(self) -> float:
        return self.completion_tokens / self.latency_s if self.latency_s else 0.0

    @property
    def passed(self) -> bool:
        return self.reward >= 0.999


def _extract_sv(text: str) -> str | None:
    m = _FENCE_SV.search(text)
    body = (m.group(1) if m else text).strip()
    return body or None


def _grade_rtl(grader_mod, rtl_text: str, hidden: Path) -> tuple[float, dict]:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sv", delete=False, encoding="utf-8") as f:
        f.write(rtl_text)
        rtl_path = Path(f.name)
    try:
        result = grader_mod.grade(Path("/tmp"), rtl_override=rtl_path, hidden_root=hidden)
        subs = result["subscores"]
        parts = {
            "functional": subs["functional"]["raw_score"],
            "synthesis": subs["synthesis"]["result"]["score"],
            "lint": subs["lint"]["raw_score"],
        }
        return float(result["reward"]), parts
    finally:
        rtl_path.unlink(missing_ok=True)


def _grade_design(candidate_sv: str, golden_sv: str) -> tuple[float, dict]:
    g = cosim_grade(candidate_sv, golden_sv)
    parts = g["parts"]
    return g["reward"], {
        "compile": parts.get("compile", 0),
        "lint": parts.get("lint", 0),
        "behavior": parts.get("behavior", 0),
    }


def run_arm(
    cli: OpenAI,
    arm: str,
    model: str,
    prompt: str,
    meta: dict,
    *,
    temperature: float = 0.0,
    max_tokens: int = 4096,
) -> NonFsmResult:
    t0 = time.time()
    resp = cli.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    latency = time.time() - t0
    text = resp.choices[0].message.content or ""
    u = resp.usage
    module = meta["module"]

    res = NonFsmResult(
        arm=arm,
        model=model,
        raw_output=text,
        prompt_tokens=getattr(u, "prompt_tokens", 0),
        completion_tokens=getattr(u, "completion_tokens", 0),
        latency_s=latency,
    )

    if arm == "DSL":
        m = _FENCE_FSM.search(text)
        dsl_src = (m.group(1) if m else text).strip()
        sv = transpile(dsl_src) if dsl_src else None
        res.code = sv
        if sv is None:
            res.note = "DSL cannot express this task (non-FSM) — transpile failed"
            return res
    else:
        res.code = _extract_sv(text)

    if not res.code:
        res.note = "no parseable code block"
        return res
    if f"module {module}" not in res.code:
        res.note = f"output missing {module} module"
        return res

    try:
        if meta["kind"] == "repair":
            grader_mod = _load_grader(meta["grader"])
            res.reward, res.parts = _grade_rtl(grader_mod, res.code, meta["hidden"])
        else:
            golden = meta["golden"].read_text(encoding="utf-8")
            res.reward, res.parts = _grade_design(res.code, golden)
    except Exception as exc:
        res.note = f"grader error: {exc}"

    return res


def _fmt(res: NonFsmResult, *, design: bool = False) -> str:
    p = res.parts or {}
    verdict = "PASS ✅" if res.passed else "FAIL ❌"
    lines = [
        f"model            : {res.model}",
        f"verdict          : {verdict}   reward={res.reward:.3f}",
    ]
    if design:
        lines += [
            f"  compiles       : {p.get('compile', 0):.0f}   (weight 0.2)",
            f"  lint-clean     : {p.get('lint', 0):.0f}   (weight 0.1)",
            f"  behaviour      : {p.get('behavior', 0):.0f}   (weight 0.7)",
        ]
    else:
        lines += [
            f"  functional     : {p.get('functional', 0):.2f}   (weight 0.50, hard cap)",
            f"  synthesis      : {p.get('synthesis', 0):.2f}",
            f"  lint           : {p.get('lint', 0):.2f}   (weight 0.20)",
        ]
    lines += [
        f"prompt tokens    : {res.prompt_tokens}",
        f"completion tokens: {res.completion_tokens}",
        f"latency          : {res.latency_s:.2f} s",
        f"speed            : {res.tokens_per_s:.1f} tok/s",
    ]
    if res.note:
        lines.append(f"note             : {res.note}")
    lines += [
        "",
        "----- raw model output -----",
        res.raw_output or "(empty)",
        "",
        "----- SystemVerilog (graded) -----",
        res.code or "(no code produced)",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Non-FSM benchmark: trained vs base")
    ap.add_argument("--task", default="stream_arb_fifo_repair", choices=list(NON_FSM_TASKS))
    ap.add_argument("--dsl-model", default=DSL_MODEL_DEFAULT)
    ap.add_argument("--trained-model", default=DSL_MODEL_DEFAULT)
    ap.add_argument("--verilog-model", default=VERILOG_MODEL_DEFAULT)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--skip-dsl", action="store_true", help="skip DSL arm (N/A for non-FSM)")
    args = ap.parse_args()

    meta = NON_FSM_TASKS[args.task]
    spec = meta["prompt"].read_text(encoding="utf-8")
    is_design = meta["kind"] == "design"
    cli = client(args.api_key)

    if is_design:
        v_prompt = verilog_prompt(spec)
        dsl_prompt_text = dsl_design_prompt(spec)
        action = "design"
    else:
        buggy = meta["rtl"].read_text(encoding="utf-8")
        v_prompt = repair_prompt(spec, buggy)
        dsl_prompt_text = dsl_repair_prompt(spec, buggy)
        action = "repair"

    print("=" * 78)
    print(f"NON-FSM TASK: {args.task}  ({action})")
    print("=" * 78)
    print(spec.strip())
    print("\n(DSL is FSM-only — non-FSM tasks are a negative control for the language.)\n")

    print(f"Running fine-tuned model (Verilog {action}) ...")
    trained = run_arm(
        cli, "Verilog", args.trained_model, v_prompt, meta,
        temperature=args.temperature,
        max_tokens=1024 if is_design else 4096,
    )
    print(f"Running base model (Verilog {action}) ...")
    base = run_arm(
        cli, "Verilog", args.verilog_model, v_prompt, meta,
        temperature=args.temperature,
        max_tokens=1024 if is_design else 4096,
    )

    dsl: NonFsmResult | None = None
    if not args.skip_dsl:
        print("Running fine-tuned model (DSL arm — expected to fail) ...")
        dsl = run_arm(
            cli, "DSL", args.dsl_model, dsl_prompt_text, meta,
            temperature=args.temperature, max_tokens=700,
        )

    label = "design" if is_design else "repair"
    print("\n" + "=" * 78)
    print(f"ARM 1 — TRAINED  ({args.trained_model})  •  Verilog {label}")
    print("=" * 78)
    print(_fmt(trained, design=is_design))
    print("=" * 78)
    print(f"ARM 2 — BASE     ({args.verilog_model})  •  Verilog {label}\n{_fmt(base, design=is_design)}")
    if dsl is not None:
        print("=" * 78)
        print(f"ARM 3 — TRAINED  ({args.dsl_model})  •  DSL (negative control)\n{_fmt(dsl, design=is_design)}")

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(
        f"  Trained (Verilog): reward {trained.reward:.3f}  "
        f"{'PASS' if trained.passed else 'FAIL'}  | "
        f"{trained.completion_tokens} tok  {trained.latency_s:.2f}s"
    )
    print(
        f"  Base (Verilog)   : reward {base.reward:.3f}  "
        f"{'PASS' if base.passed else 'FAIL'}  | "
        f"{base.completion_tokens} tok  {base.latency_s:.2f}s"
    )
    if dsl is not None:
        print(
            f"  Trained (DSL)    : reward {dsl.reward:.3f}  "
            f"{'PASS' if dsl.passed else 'FAIL'}  | "
            f"{dsl.completion_tokens} tok  | {dsl.note or 'transpiled'}"
        )


if __name__ == "__main__":
    main()
