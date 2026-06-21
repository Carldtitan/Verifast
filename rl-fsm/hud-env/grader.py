"""Cosim grader: score a model's SystemVerilog against the task's golden.

reward = 0.2 (compiles) + 0.1 (lint-clean) + 0.7 (behavioral match vs golden)

Behavioral match: build a tiny SV testbench that instantiates BOTH the candidate
(as `dut`) and the golden (as `ref`), drives identical pseudo-random inputs each
cycle after reset, and flags any cycle where any output differs. Runs under
verilator --binary. The candidate is renamed to avoid a module-name clash with
golden (both are generated with the same module name).

Requires verilator on PATH (OSS CAD Suite). Designed to run inside the HUD env or
the RL reward path; pure-CPU.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

_PORT_RE = re.compile(r"(input|output)\s+logic\s*(\[(\d+):(\d+)\])?\s*(\w+)")


def _parse_ports(golden_sv: str) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """Return (inputs, outputs) as (name, width), excluding clk/rst."""
    header = golden_sv.split(");", 1)[0]
    ins: list[tuple[str, int]] = []
    outs: list[tuple[str, int]] = []
    for m in _PORT_RE.finditer(header):
        direction, _rng, hi, lo, name = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        width = (int(hi) - int(lo) + 1) if hi is not None else 1
        if name in ("clk", "rst"):
            continue
        (ins if direction == "input" else outs).append((name, width))
    return ins, outs


def _rename_module(sv: str, new_name: str) -> str:
    return re.sub(r"\bmodule\s+\w+", f"module {new_name}", sv, count=1)


def _build_tb(ins, outs, cycles: int = 200) -> str:
    portmap = lambda inst: ", ".join(
        [".clk(clk)", ".rst(rst)"]
        + [f".{n}({n})" for n, _ in ins]
        + [f".{n}({inst}_{n})" for n, _ in outs]
    )
    decls = []
    for n, w in ins:
        decls.append(f"  logic {'' if w == 1 else f'[{w-1}:0] '}{n};")
    for n, w in outs:
        decls.append(f"  logic {'' if w == 1 else f'[{w-1}:0] '}dut_{n};")
        decls.append(f"  logic {'' if w == 1 else f'[{w-1}:0] '}ref_{n};")
    drive = "\n".join(f"    {n} = $random;" for n, _ in ins)
    cmp = " || ".join(f"(dut_{n} !== ref_{n})" for n, _ in outs) or "1'b0"
    return f"""
module tb;
  logic clk = 0; logic rst = 1;
{chr(10).join(decls)}
  integer i;
  integer fails = 0;
  dut  d ({portmap('dut')});
  ref_ r ({portmap('ref')});
  always #5 clk = ~clk;
  initial begin
    @(negedge clk); @(negedge clk); rst = 0;
    for (i = 0; i < {cycles}; i = i + 1) begin
{drive}
      @(negedge clk);
      if ({cmp}) fails = fails + 1;
    end
    if (fails == 0) $display("COSIM_PASS");
    else            $display("COSIM_FAIL %0d", fails);
    $finish;
  end
endmodule
"""


def _run(cmd, cwd, timeout=120):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def grade(candidate_sv: str, golden_sv: str) -> dict:
    ins, outs = _parse_ports(golden_sv)
    reward = 0.0
    parts = {"compile": 0.0, "lint": 0.0, "behavior": 0.0}
    with tempfile.TemporaryDirectory(prefix="fsm-grade-") as td:
        work = Path(td)
        cand = _rename_module(candidate_sv, "dut")
        gold = _rename_module(golden_sv, "ref_")
        (work / "dut.sv").write_text(cand, encoding="utf-8")
        (work / "ref.sv").write_text(gold, encoding="utf-8")
        (work / "tb.sv").write_text(_build_tb(ins, outs), encoding="utf-8")

        # 1. compile (lint-allowed) — does the candidate build at all?
        c = _run(["verilator", "--binary", "--timing", "-Wno-lint", "-Wno-INITIALDLY",
                  "--top-module", "tb", "-o", "sim", "tb.sv", "dut.sv", "ref.sv"], work)
        if c.returncode != 0:
            return {"reward": 0.0, "parts": parts, "log": c.stdout + c.stderr}
        parts["compile"] = 1.0

        # 2. lint-clean (candidate alone, -Wall)
        lint = _run(["verilator", "--lint-only", "-Wall", "--top-module", "dut", "dut.sv"], work)
        warns = [ln for ln in (lint.stdout + lint.stderr).splitlines() if "%Warning" in ln or "%Error" in ln]
        if lint.returncode == 0 and not warns:
            parts["lint"] = 1.0

        # 3. behavioral cosim vs golden
        sim = _run([str(work / "obj_dir" / "sim") if (work / "obj_dir" / "sim").exists()
                    else str(work / "sim")], work, timeout=60)
        if "COSIM_PASS" in sim.stdout:
            parts["behavior"] = 1.0

    reward = 0.2 * parts["compile"] + 0.1 * parts["lint"] + 0.7 * parts["behavior"]
    return {"reward": round(reward, 4), "parts": parts}


if __name__ == "__main__":
    import sys
    cand = Path(sys.argv[1]).read_text(encoding="utf-8")
    gold = Path(sys.argv[2]).read_text(encoding="utf-8")
    print(grade(cand, gold))
