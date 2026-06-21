"""Grade a DSL-arm run: extract the .fsm, transpile with the FROZEN transpiler, cosim.

A defect in the .fsm (bad syntax or a safety-rule violation) means the transpiler
rejects it -> reward 0 (compile fail), exactly like a Verilog that won't compile.

Usage (WSL, verilator on PATH):
    python grade_dsl_run.py --run-dir "<runs/<tag>/heldout>" --tasks-dir "<held_out>"
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hud_env"))
sys.path.insert(0, str(ROOT.parent / "fsm-dsl-transpiler"))

from grader import grade                       # noqa: E402
from transpiler.parser import parse            # noqa: E402
from transpiler.ast import build_ast           # noqa: E402
from transpiler.safety import check            # noqa: E402
from transpiler.codegen import generate        # noqa: E402

_FENCE = re.compile(r"```(?:fsm|dsl)?\s*(.*?)```", re.DOTALL)


def extract_fsm(ans: str) -> str:
    m = _FENCE.search(ans)
    return (m.group(1) if m else ans).strip()


def transpile(fsm_src: str) -> str | None:
    """Return generated SystemVerilog, or None if the .fsm is invalid/unsafe."""
    try:
        program = build_ast(parse(fsm_src, file="<gen>"), source_file="<gen>")
        if check(program):
            return None
        return generate(program.machines[0])
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--tasks-dir", required=True)
    args = ap.parse_args()
    run, tasks = Path(args.run_dir), Path(args.tasks_dir)

    rows = []
    transpiled_ok = 0
    for ans_file in sorted(run.glob("task_*.txt")):
        name = ans_file.stem
        golden_p = tasks / name / "golden.sv"
        if not golden_p.exists():
            continue
        fsm_src = extract_fsm(ans_file.read_text(encoding="utf-8"))
        sv = transpile(fsm_src)
        if sv is None:
            r = {"reward": 0.0, "parts": {"compile": 0, "lint": 0, "behavior": 0},
                 "note": "invalid/unsafe DSL -> rejected by transpiler"}
        else:
            transpiled_ok += 1
            r = grade(sv, golden_p.read_text(encoding="utf-8"))
        rows.append((name, r))
        p = r["parts"]
        print(f"{name}: reward={r['reward']:.2f} transpiled={'Y' if sv else 'N'} "
              f"compile={p['compile']} lint={p['lint']} behavior={p['behavior']}")

    n = len(rows) or 1
    functional = sum(1 for _, r in rows if r["parts"]["behavior"] == 1.0)
    fully_clean = sum(1 for _, r in rows if r["reward"] >= 0.999)
    avg = sum(r["reward"] for _, r in rows) / n
    summary = {
        "tasks": len(rows),
        "transpiled_ok": transpiled_ok / n,
        "functional_pass_at_1": functional / n,
        "fully_clean_pass_at_1": fully_clean / n,
        "avg_reward": avg,
    }
    (run.parent / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\n==== DSL ARM RESULTS ====")
    print(f"transpiled (valid DSL):       {transpiled_ok}/{len(rows)}")
    print(f"FUNCTIONAL pass@1 (headline): {functional}/{len(rows)} = {100*functional/n:.1f}%")
    print(f"fully-clean pass@1:           {fully_clean}/{len(rows)} = {100*fully_clean/n:.1f}%")
    print(f"avg blended reward:           {avg:.3f}")


if __name__ == "__main__":
    main()
