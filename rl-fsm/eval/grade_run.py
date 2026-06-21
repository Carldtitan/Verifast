"""Grade a model run's answers against the task goldens. Model-agnostic.

Usage (run in WSL with verilator on PATH):
    python grade_run.py --run-dir "<runs/<tag>/heldout>" --tasks-dir "<held_out>"

Reports functional pass@1 (the headline scoreboard) plus the reward breakdown,
and writes results.json next to the run dir.
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hud_env"))
from grader import grade  # noqa: E402

_FENCE = re.compile(r"```(?:systemverilog|verilog|sv)?\s*(.*?)```", re.DOTALL)


def extract(ans: str) -> str:
    m = _FENCE.search(ans)
    return (m.group(1) if m else ans).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--tasks-dir", required=True)
    args = ap.parse_args()

    run = Path(args.run_dir)
    tasks = Path(args.tasks_dir)
    rows = []
    for ans_file in sorted(run.glob("task_*.txt")):
        name = ans_file.stem
        golden_p = tasks / name / "golden.sv"
        if not golden_p.exists():
            continue
        cand = extract(ans_file.read_text(encoding="utf-8"))
        golden = golden_p.read_text(encoding="utf-8")
        try:
            r = grade(cand, golden)
        except Exception as e:
            r = {"reward": 0.0, "parts": {"compile": 0, "lint": 0, "behavior": 0}, "err": str(e)}
        rows.append((name, r))
        p = r["parts"]
        print(f"{name}: reward={r['reward']:.2f}  compile={p['compile']} lint={p['lint']} behavior={p['behavior']}")

    n = len(rows) or 1
    functional = sum(1 for _, r in rows if r["parts"]["behavior"] == 1.0)
    fully_clean = sum(1 for _, r in rows if r["reward"] >= 0.999)
    compiled = sum(1 for _, r in rows if r["parts"]["compile"] == 1.0)
    avg = sum(r["reward"] for _, r in rows) / n

    summary = {
        "tasks": len(rows),
        "functional_pass_at_1": functional / n,
        "fully_clean_pass_at_1": fully_clean / n,
        "compiled": compiled / n,
        "avg_reward": avg,
    }
    (run.parent / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\n==== RESULTS ====")
    print(f"FUNCTIONAL pass@1 (headline): {functional}/{len(rows)} = {100*functional/n:.1f}%")
    print(f"fully-clean pass@1:           {fully_clean}/{len(rows)} = {100*fully_clean/n:.1f}%")
    print(f"compiled:                     {compiled}/{len(rows)}")
    print(f"avg blended reward (signal):  {avg:.3f}")


if __name__ == "__main__":
    main()
