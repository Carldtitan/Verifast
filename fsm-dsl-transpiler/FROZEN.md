# FROZEN — FSM_DSL Transpiler Frozen Record

**Transpiler version identifier:** FSM_DSL transpiler v0.1.0
(`pyproject.toml` `[project] version = "0.1.0"`; `transpiler.__version__ == "0.1.0"`)

**Freeze date (ISO 8601):** 2026-06-20

**Freeze status:** ✅ tool-validated — the lint, latch-freedom, and golden
behavioral-equivalence gates were **executed and passed** under the OSS CAD
Suite (not merely authored). See "Tool-validated run" below.

This record is produced on a passing test run (Req 21.1). A failing run neither
creates nor modifies it (Req 21.2, 21.5).

## Tool-validated run

Executed in WSL2 (Ubuntu 24.04.1 LTS) with the toolchain on `PATH`:

| Tool      | Version              |
| --------- | -------------------- |
| Verilator | 5.020                |
| Yosys     | 0.33                 |
| Icarus    | 12.0 (`iverilog`/`vvp`) |
| Python    | 3.12                 |

```
FSM_REQUIRE_TOOLS=1 uv run pytest
=> 219 passed, 0 skipped   (exit 0)
```

With the tools present **every gate executed and passed**, including:

1. **Golden behavioral equivalence** — `test_golden_behavioral_equivalence`
   co-simulated each generated module against its `golden/*.sv` over ≥ 1000
   deterministically-seeded cycles, comparing every output port every cycle
   after reset deassertion. All three examples match cycle-for-cycle.
2. **Lint** — `verilator --lint-only -Wall` reported zero warnings/errors for
   every generated module and every golden, and for the property gate at a
   raised pre-freeze sweep of `max_examples=150`.
3. **Latch-freedom** — Yosys synthesis reported `$dlatch` count == 0 for every
   generated module and every golden (property gate likewise at 150).
4. **Reset precedence** — confirmed in `iverilog` simulation.

A developer run on the Windows host (no toolchain on `PATH`) is also green —
**193 passed, 26 skipped** — where the 26 skips are exactly the tool-bound gates
above; they skip cleanly rather than fail when the OSS CAD Suite is absent.

## Fixes folded into this freeze

Running the real tools surfaced (and we fixed, without suppressing any warning)
the following SystemVerilog-correctness corners:

- **Unused / partially-read inputs** (`UNUSEDSIGNAL`). A declared input that no
  guard reads, or a vector input read only through bit-selects (leaving some
  bits unread), is **legal** and not rejected. The generator emits a targeted,
  name-exempt "intentionally unused" read of the whole signal
  (`wire _unused_ok = &{1'b0, ...};`) so the module is `-Wall` clean. `-Wall` is
  never dropped and no blanket `-Wno-UNUSEDSIGNAL` is used. (Spec §2.2, table
  row 12.)
- **Guard width** (`WIDTH` / `WIDTHTRUNC` / `CMPCONST`). Guards are carried as a
  typed expression tree and rendered width-correctly: a multi-bit signal in a
  boolean context is reduced with `|` (`(|f)`), comparison literals are sized to
  the signal width (`f == 3'd5`), over-wide literals are rejected at compile
  time, and width-trivial comparisons (e.g. `e <= 3` on a 2-bit `e`) are folded
  to `1'b1`/`1'b0`. No width/comparison warning is suppressed. (Spec §2.7, table
  row 13.)

Regression tests for all of the above live in `tests/test_transpiler.py`
(`test_unused_input_*`, `test_partially_used_multibit_input_is_waived`,
`test_multibit_guard_*`, `test_overwide_comparison_literal_is_rejected`).

## Re-freeze policy (Req 21.4, 21.5)

The transpiler is **frozen**. It is modified **only through a re-freeze**:

1. re-run the **full Test_Harness** with the toolchain on `PATH`
   (`FSM_REQUIRE_TOOLS=1 uv run pytest`) to a **passing result**, optionally
   raising the tool-bounded property `max_examples` to ~100–200 for a wider
   sweep, and
2. update the recorded **version identifier** and **freeze date** here.

The transpiler is **never modified silently** during experiments. Any change in
downstream model pass-rate must be attributable to language (or example)
changes, not transpiler drift.
